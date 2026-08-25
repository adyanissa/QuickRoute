import { useCallback, useEffect, useRef, useState } from 'react';
import jsQR from 'jsqr';
import '../styles/QrScanner.css';

// Camera QR reader.
//
// WHAT IT IS NOT
// --------------
// It is NOT a location resolver. This component's entire output is the
// raw text it read off a QR code; it calls `onResult(text)` once and
// stops. Deciding what that text means — resolving it, validating it,
// relocating, confirming arrival, rejecting it — stays exactly where it
// already lives (IndoorNavigationScreen's existing resolve handler, which
// calls the existing resolveLocationCode API). A scanned code and a typed
// code therefore travel the identical path, and there is no second
// location-resolution system.
//
// HOW IT READS
// ------------
// Two decoders, preferring the browser's own:
//
//   BarcodeDetector  — native, hardware-accelerated, no main-thread cost.
//                      Chrome/Edge/Android. Used when present.
//   jsQR             — pure JS fallback over a canvas frame. Safari,
//                      Firefox, and anything else.
//
// Either way the frame loop is throttled and stops the moment a code is
// found or the component unmounts, so the camera track is always
// released.

const SCAN_INTERVAL_MS = 180;

const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);

/**
 * @param {(text: string) => void} onResult  called once with the decoded text
 * @param {() => void}             onClose   user dismissed the scanner
 * @param {object}                 labels    already-translated strings
 */
const QrScanner = ({ onResult, onClose, labels }) => {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);
  const detectorRef = useRef(null);
  // Guards against a second onResult after a code is found but before the
  // parent unmounts us — and against React StrictMode's double effect.
  const doneRef = useRef(false);

  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {
          // Already stopped — releasing twice is not an error worth
          // surfacing to someone trying to find a room.
        }
      });
      streamRef.current = null;
    }
  }, []);

  const succeed = useCallback(
    (text) => {
      const value = (text ?? '').trim();
      if (!value || doneRef.current) return;

      doneRef.current = true;
      stop();
      onResult?.(value);
    },
    [onResult, stop],
  );

  useEffect(() => {
    let cancelled = false;
    doneRef.current = false;

    const readFrame = async () => {
      const video = videoRef.current;

      if (cancelled || doneRef.current || !video || video.readyState < 2) return;

      // 1. Native detector, when the browser has one.
      if (detectorRef.current) {
        try {
          const found = await detectorRef.current.detect(video);
          if (found?.length) {
            succeed(found[0].rawValue);
            return;
          }
        } catch {
          // A transient detect() failure (e.g. the frame was not ready)
          // is not fatal — the next tick tries again, and jsQR below
          // still runs as a safety net.
        }
        return;
      }

      // 2. jsQR over a downscaled frame.
      const canvas = canvasRef.current;
      if (!canvas) return;

      const width = video.videoWidth;
      const height = video.videoHeight;
      if (!width || !height) return;

      canvas.width = width;
      canvas.height = height;

      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) return;

      context.drawImage(video, 0, 0, width, height);

      let imageData;
      try {
        imageData = context.getImageData(0, 0, width, height);
      } catch {
        return;
      }

      const result = jsQR(imageData.data, width, height, {
        inversionAttempts: 'dontInvert',
      });

      if (result?.data) succeed(result.data);
    };

    const start = async () => {
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        setError(labels.unsupported);
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          // The rear camera is the one pointed at a door sign.
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        });

        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;

        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          video.setAttribute('playsinline', 'true');
          await video.play().catch(() => {});
        }

        if (typeof window !== 'undefined' && 'BarcodeDetector' in window) {
          try {
            detectorRef.current = new window.BarcodeDetector({
              formats: ['qr_code'],
            });
          } catch {
            detectorRef.current = null;
          }
        }

        if (!cancelled) {
          setReady(true);
          timerRef.current = setInterval(readFrame, SCAN_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;

        // A refused permission is the common case and deserves its own
        // wording; anything else is reported as "camera unavailable".
        const denied =
          err?.name === 'NotAllowedError' || err?.name === 'SecurityError';
        setError(denied ? labels.denied : labels.unavailable);
      }
    };

    start();

    return () => {
      cancelled = true;
      stop();
    };
    // labels is a fresh object per render; only its identity would change,
    // never the flow. Restarting the camera on a language switch would be
    // worse than showing the previous language's error string.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stop, succeed]);

  return (
    <div className="qrs-overlay" role="dialog" aria-modal="true" aria-label={labels.title}>
      <div className="qrs-panel">
        <div className="qrs-head">
          <p className="qrs-title">{labels.title}</p>
          <button
            type="button"
            className="qrs-close"
            onClick={onClose}
            aria-label={labels.cancel}
          >
            <CloseIcon />
          </button>
        </div>

        {error ? (
          <div className="qrs-error">
            <p>{error}</p>
            <p className="qrs-error-hint">{labels.errorHint}</p>
          </div>
        ) : (
          <div className="qrs-stage">
            <video ref={videoRef} className="qrs-video" muted playsInline />
            <div className="qrs-frame" aria-hidden="true">
              <span /><span /><span /><span />
            </div>
            {!ready && <p className="qrs-status">{labels.starting}</p>}
          </div>
        )}

        <canvas ref={canvasRef} className="qrs-canvas" aria-hidden="true" />

        <p className="qrs-hint">{labels.hint}</p>

        <button type="button" className="qrs-cancel" onClick={onClose}>
          {labels.cancel}
        </button>
      </div>
    </div>
  );
};

export default QrScanner;
