import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  getLatestMapAnalysis,
  startMapAnalysis,
  retryAnalysis,
  isMapAnalysisMockEnabled,
} from '../api/mapAnalysisApi';
import { statusBucket, canRetry, canReview } from '../utils/mapAnalysisHelpers';

// Small, self-contained status card for Map Management's map preview area
// (Section 13: "After upload, Map Management must show an analysis
// status card"). Deliberately isolated into its own component/file
// (rather than added inline into the very large AdminMapScreen.jsx) so it
// can be developed, tested, and reasoned about independently, and so its
// own data-fetching/polling never risks the surrounding screen's state.
//
// This card only ever DISPLAYS status and offers Review/Retry/Run Again —
// it never itself writes AI drafts, edits, or publishes anything.

const UI = {
  en: {
    title: 'Semantic Analysis',
    mock: 'Mock mode',
    queued: 'Queued',
    processing: (p) => `Analyzing… ${p}%`,
    completed: 'Analysis complete',
    failed: 'Analysis failed',
    invalidOutput: 'Invalid AI output',
    configRequired: 'Configuration required',
    cancelled: 'Cancelled',
    superseded: 'Superseded by a newer analysis',
    none: 'No analysis has been run for this map yet.',
    review: 'Review Analysis',
    retry: 'Retry',
    runAgain: 'Run Again',
    start: 'Start Analysis',
    viewError: 'View Error',
    promptVersion: 'Prompt version',
  },
  ar: {
    title: 'التحليل الدلالي',
    mock: 'وضع تجريبي',
    queued: 'في الانتظار',
    processing: (p) => `جارٍ التحليل… ${p}%`,
    completed: 'اكتمل التحليل',
    failed: 'فشل التحليل',
    invalidOutput: 'مخرجات الذكاء الاصطناعي غير صالحة',
    configRequired: 'مطلوب إعداد',
    cancelled: 'تم الإلغاء',
    superseded: 'تم استبداله بتحليل أحدث',
    none: 'لم يتم تشغيل أي تحليل لهذه الخريطة بعد.',
    review: 'مراجعة التحليل',
    retry: 'إعادة المحاولة',
    runAgain: 'تشغيل مرة أخرى',
    start: 'بدء التحليل',
    viewError: 'عرض الخطأ',
    promptVersion: 'إصدار الطلب',
  },
  he: {
    title: 'ניתוח סמנטי',
    mock: 'מצב הדגמה',
    queued: 'בהמתנה',
    processing: (p) => `מנתח… ${p}%`,
    completed: 'הניתוח הושלם',
    failed: 'הניתוח נכשל',
    invalidOutput: 'פלט AI לא תקין',
    configRequired: 'נדרשת תצורה',
    cancelled: 'בוטל',
    superseded: 'הוחלף בניתוח חדש יותר',
    none: 'טרם הופעל ניתוח למפה זו.',
    review: 'סקור ניתוח',
    retry: 'נסה שוב',
    runAgain: 'הפעל שוב',
    start: 'התחל ניתוח',
    viewError: 'הצג שגיאה',
    promptVersion: 'גרסת הנחיה',
  },
};

const STATUS_LABEL_KEY = {
  queued: 'queued',
  processing: 'processing',
  completed: 'completed',
  failed: 'failed',
  invalid_output: 'invalidOutput',
  configuration_required: 'configRequired',
  cancelled: 'cancelled',
  superseded: 'superseded',
};

const BUCKET_COLOR = {
  success: '#1f9d55',
  in_progress: '#b47b09',
  configuration: '#7a5cff',
  error: '#a92323',
  inactive: '#6c7a8c',
  unknown: '#6c7a8c',
};

export default function SemanticAnalysisStatusCard({ mapId, lang = 'en' }) {
  const t = UI[lang] || UI.en;
  const navigate = useNavigate();
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showError, setShowError] = useState(false);

  const load = useCallback(async () => {
    if (!mapId) {
      setAnalysis(null);
      return;
    }
    setLoading(true);
    try {
      const latest = await getLatestMapAnalysis(mapId);
      setAnalysis(latest);
    } catch {
      setAnalysis(null);
    } finally {
      setLoading(false);
    }
  }, [mapId]);

  useEffect(() => {
    load();
  }, [load]);

  // Light polling only while genuinely in flight — never for a terminal
  // status, so this never keeps hitting the backend for a map that's
  // done (completed/failed/etc.).
  useEffect(() => {
    if (!analysis || !['queued', 'processing'].includes(analysis.status)) return undefined;
    const timer = setTimeout(load, 2500);
    return () => clearTimeout(timer);
  }, [analysis, load]);

  if (!mapId) return null;

  const handleStartOrRunAgain = async () => {
    setBusy(true);
    try {
      const started = await startMapAnalysis(mapId, { force: Boolean(analysis) });
      setAnalysis(started);
    } catch {
      // Swallow — the card's own status will simply stay whatever it was;
      // a hard failure here is not worth a modal for a background action.
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!analysis?.analysisId) return;
    setBusy(true);
    try {
      const updated = await retryAnalysis(analysis.analysisId);
      setAnalysis(updated);
    } catch {
      // no-op — card just keeps showing the last known status
    } finally {
      setBusy(false);
    }
  };

  const bucket = analysis ? statusBucket(analysis.status) : 'unknown';
  const color = BUCKET_COLOR[bucket] || BUCKET_COLOR.unknown;
  const labelKey = analysis ? STATUS_LABEL_KEY[analysis.status] : null;

  return (
    <div
      className="adm-form-card"
      style={{ marginTop: 10, marginBottom: 10, padding: '10px 14px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 13 }}>{t.title}</span>
          {isMapAnalysisMockEnabled() && (
            <span style={{ fontSize: 11, background: '#fff3cd', color: '#8a6116', borderRadius: 6, padding: '2px 6px' }}>
              {t.mock}
            </span>
          )}
          {!loading && (
            <span style={{ fontSize: 12.5, color, fontWeight: 600 }}>
              {analysis
                ? labelKey === 'processing'
                  ? t.processing(analysis.progress || 0)
                  : t[labelKey] || analysis.status
                : t.none}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {analysis?.promptVersion && (
            <span style={{ fontSize: 11, color: '#6c7a8c' }} title={analysis.promptSha256 || ''}>
              {t.promptVersion}: {analysis.promptVersion}
            </span>
          )}
          {analysis && canReview(analysis.status) && (
            <button
              type="button"
              className="adm-btn adm-btn-secondary"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={() => navigate(`/admin/map-analysis?mapId=${mapId}&analysisId=${analysis.analysisId}`)}
            >
              {t.review}
            </button>
          )}
          {analysis && canRetry(analysis.status) && (
            <button
              type="button"
              className="adm-btn adm-btn-secondary"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={handleRetry}
              disabled={busy}
            >
              {t.retry}
            </button>
          )}
          {analysis?.errorMessage && (
            <button
              type="button"
              className="adm-icon-btn"
              style={{ fontSize: 12 }}
              onClick={() => setShowError((v) => !v)}
              title={t.viewError}
            >
              {t.viewError}
            </button>
          )}
          {!analysis && (
            <button
              type="button"
              className="adm-btn adm-btn-secondary"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={handleStartOrRunAgain}
              disabled={busy}
            >
              {t.start}
            </button>
          )}
          {analysis && ['completed', 'failed', 'cancelled'].includes(analysis.status) && (
            <button
              type="button"
              className="adm-btn adm-btn-secondary"
              style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={handleStartOrRunAgain}
              disabled={busy}
            >
              {t.runAgain}
            </button>
          )}
        </div>
      </div>

      {showError && analysis?.errorMessage && (
        <div style={{ marginTop: 8, fontSize: 12, color: '#a92323', background: '#ffe9e9', borderRadius: 8, padding: '6px 10px' }}>
          {analysis.errorMessage}
        </div>
      )}
    </div>
  );
}
