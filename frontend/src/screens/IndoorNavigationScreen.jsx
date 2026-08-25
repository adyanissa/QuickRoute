import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { getLocalizedText } from '../utils/localization';
import { formatFloor } from '../components/DestinationCard';
import { ROUTES } from '../config/routes';
import QuickRouteLogo from '../components/QuickRouteLogo';
import RouteSteps from '../components/RouteSteps';
import BackButton from '../components/BackButton';
import { getPublicRoutePoints, getPublicRoutePointById } from '../api/routePointsApi';
import { resolveLocationCode } from '../api/locationCodesApi';
import QrScanner from '../components/QrScanner';
import { calculateMultiFloorRoute } from '../api/navigationApi';
import { getDestinationRoutePointId } from '../utils/destinationPlacement';
import {
  buildStartLocationRecord,
  classifyScannedLocation,
  extractLocationCode,
  isScanInActiveBuilding,
} from '../utils/locationScan';
import {
  groupInstructionsByFloor,
  getTransitionInstructions,
  getFloorSegments,
  getTransitionSegments,
  instructionToStep,
  buildRouteStateKey,
  isFloorComplete,
  computeOverallProgress,
  getNextMeaningfulInstruction,
} from '../utils/multiFloorRouteHelpers';
import '../styles/IndoorNavigationScreen.css';

// Professional end-user navigation redesign (this task): distance-in-meters,
// ETA, estimated walking time, estimated step count, and any "remaining"
// metres/time are computed exactly as before (routeResult, overallProgress
// below still carry the real backend values) but are DELIBERATELY never
// rendered anywhere on this screen — the demo maps' calibration isn't
// trustworthy enough to show a number that looks precise. See
// utils/routeHelpers.js's formatDistance/formatTime/estimateSteps, which
// remain fully intact (and fully unit-tested — routeHelpers.test.mjs) for
// any future/other consumer; they are simply not imported/called here
// anymore.

// Same key BarcodeEntryScreen writes to after a location code resolves.
// A resolved start is used regardless of which floor it happens to be on
// now that navigation is multi-floor-aware — it no longer has to match
// "the current map" the way the old single-floor flow required.
const START_LOCATION_KEY = 'quickroute_start_location';

// In-progress navigation state (active floor, completed steps) is
// persisted per exact route request (PHASE 13 requirement #10) so a
// refresh mid-navigation doesn't silently drop the user back to step one.
const NAV_STATE_STORAGE_PREFIX = 'quickroute_nav_state:';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

// ── Translations ──────────────────────────────────────────────────────────────
const UI = {
  en: {
    back:        'Back',
    optionCode:   'Enter room code',
    optionScan:   'Scan a QR code',
    verify:       'Verify',
    confirmTitle: 'Verify / update your location',
    confirmHint:  'Enter a room code or scan its QR to confirm where you are. If you are somewhere else, your route is recalculated from there.',
    goingTo:      'Going to',
    scanQr:       'Scan QR',
    rescanCtaHint: 'Enter a room code or scan a QR to correct your position',
    scanTitle:    'Scan a room QR code',
    scanHint:     'Point the camera at the QuickRoute code on the door or wall.',
    scanStarting: 'Starting camera...',
    scanDenied:   'Camera access was blocked.',
    scanUnavailable: 'The camera could not be started.',
    scanUnsupported: 'This browser cannot use the camera.',
    scanErrorHint: 'You can still enter the code by hand.',
    destination: 'Your Destination',
    routeReady:  'Route ready',
    navigating:  'Navigating',
    arrived:     'Arrived',
    startNav:    'Start Navigation',
    exitNav:     'Exit Navigation',
    endNav:      'End Navigation',
    you:         'You',
    directions:  'Directions',
    navHint:     'Tap ✓ on each step when completed',
    arrivedTitle:'You have reached your destination',
    // Mid-journey relocation / arrival confirmation by room QR.
    rescanCta:    'Update my current location',
    rescanTitle: 'Scan or enter a room code',
    rescanHint:  'Your route is recalculated from wherever you are now',
    rescanPlaceholder: 'Room code',
    rescanSubmit:'Update my location',
    rescanCancel:'Cancel',
    rescanSame:  'You are already at this location',
    rescanInvalid:'That code could not be found',
    rescanOtherBuilding:'That code belongs to a different building',
    relocatedTo: (label) => `Location updated: ${label}`,
    arrivedSub:  'Destination reached',
    loadingRoute:'Preparing your route...',
    noRoute:     'No available route was found',
    noRouteHint: 'This destination has not been connected to the navigation network yet',
    noStartPoint:'No entrance point has been set up for this building yet',
    // Truthful status badge (Section 3) — replaces any distance/ETA claim.
    // Never worded as "exact"/"accurate" — only that a shortest route was
    // computed, which is always true regardless of map calibration quality.
    toLabel:     'To',
    nextLabel:   'Next',
    youAreNowOnFloor: (label) => `You are now on ${label}`,
    stopNav:     'Stop navigation',
    floorsLabel: (n) => (n === 1 ? '1 floor' : `${n} floors`),
    accessibleYes: 'Wheelchair accessible',
    accessibleNo:  'Not fully accessible',
    modeShortest: 'Shortest',
    modeFastest:  'Fastest',
    modeAccessible: 'Accessible',
    // Section 7 — single-choice vertical-transport preference, replacing
    // the old separate avoid-stairs/avoid-escalators/prefer-elevators
    // checkboxes on this screen (the backend still accepts those three
    // booleans unchanged for other/older callers — see
    // navigationApi.js/navigation_routes.py comments).
    vertPrefAny: 'Any available route',
    vertPrefElevator: 'Prefer elevator',
    vertPrefStairs: 'Prefer stairs',
    floorTabPrefix: 'Floor',
    continueTo: (label) => `Continue to Floor ${label}`,
    reachedFloor: (label) => `I reached Floor ${label}`,
    stepOf: (i, n) => `Step ${i} of ${n}`,
    stepsRemaining: (n) => (n === 1 ? '1 step remaining' : `${n} steps remaining`),
    previousStep: 'Previous',
    reachedStep: 'Reached — Next',
    repeatStep: 'Repeat instruction',
    remainingTime: 'Remaining',
    remainingDistance: 'left',
    progressHint: 'Progress updates when you confirm each navigation step.',
    startLabel: 'Starting point',
    currentFloorLabel: 'Current floor',
    destFloorLabel: 'Destination floor',
    routePrefLabel: 'Route preference',
    totalTimeLabel: 'Estimated total time',
    totalDistanceLabel: 'Total distance',
    connectorElevator: 'Elevator',
    connectorStairs: 'Stairs',
    connectorEscalator: 'Escalator',
    connectorRamp: 'Ramp',
    connectorGeneric: 'Floor transition',
    estimatedTransitionTime: 'Estimated time',
    elapsedTime: 'Elapsed time',
    estimatedJourneyTime: 'Estimated journey time',
    // Display-only walking-step estimate (never stored, never a routing
    // weight — see utils/routeHelpers.js's estimateSteps). Always
    // rendered with an explicit "(est.)" so it's never mistaken for a
    // measured value the way the meters distance next to it is.
    estimatedSteps: (n) => `~${n} steps (est.)`,
  },
  ar: {
    back:        'رجوع',
    optionCode:   'إدخال رمز الغرفة',
    optionScan:   'مسح رمز QR',
    verify:       'تحقق',
    confirmTitle: 'تحقّق من موقعك أو حدّثه',
    confirmHint:  'أدخل رمز الغرفة أو امسح رمز QR لتأكيد مكانك. إذا كنت في مكان آخر، تتم إعادة حساب مسارك من هناك.',
    goingTo:      'الوجهة',
    scanQr:       'مسح رمز QR',
    rescanCtaHint: 'أدخل رمز الغرفة أو امسح رمز QR لتصحيح موقعك',
    scanTitle:    'امسح رمز QR الخاص بالغرفة',
    scanHint:     'وجّه الكاميرا نحو رمز QuickRoute على الباب أو الجدار.',
    scanStarting: 'جاري تشغيل الكاميرا...',
    scanDenied:   'تم حظر الوصول إلى الكاميرا.',
    scanUnavailable: 'تعذّر تشغيل الكاميرا.',
    scanUnsupported: 'هذا المتصفح لا يدعم استخدام الكاميرا.',
    scanErrorHint: 'لا يزال بإمكانك إدخال الرمز يدويًا.',
    destination: 'وجهتك',
    routeReady:  'المسار جاهز',
    navigating:  'جارٍ التنقل',
    arrived:     'وصلت',
    startNav:    'ابدأ التنقل',
    exitNav:     'إنهاء التنقل',
    endNav:      'إنهاء التنقل',
    you:         'أنت',
    directions:  'التعليمات',
    navHint:     'اضغط ✓ بعد إتمام كل خطوة',
    arrivedTitle:'وصلتِ إلى وجهتك',
    rescanCta:    'تحديث موقعي الحالي',
    rescanTitle: 'امسح أو أدخل رمز الغرفة',
    rescanHint:  'سيتم إعادة حساب المسار من موقعك الحالي',
    rescanPlaceholder: 'رمز الغرفة',
    rescanSubmit:'تحديث موقعي',
    rescanCancel:'إلغاء',
    rescanSame:  'أنت بالفعل في هذا الموقع',
    rescanInvalid:'تعذر العثور على هذا الرمز',
    rescanOtherBuilding:'هذا الرمز يخص مبنى آخر',
    relocatedTo: (label) => `تم تحديث الموقع: ${label}`,
    arrivedSub:  'تم الوصول إلى الوجهة',
    loadingRoute:'جارٍ تحضير المسار...',
    noRoute:     'لم يتم العثور على مسار متاح',
    noRouteHint: 'لم يتم ربط هذه الوجهة بشبكة التنقل بعد',
    noStartPoint:'لم يتم إعداد نقطة دخول لهذا المبنى بعد',
    toLabel:     'إلى',
    nextLabel:   'التالي',
    youAreNowOnFloor: (label) => `أنتِ الآن في ${label}`,
    stopNav:     'إيقاف التنقل',
    floorsLabel: (n) => `${n} طوابق`,
    accessibleYes: 'يمكن الوصول بالكرسي المتحرك',
    accessibleNo:  'غير مهيأ بالكامل لذوي الاحتياجات',
    modeShortest: 'الأقصر',
    modeFastest:  'الأسرع',
    modeAccessible: 'المسار المهيأ',
    vertPrefAny: 'أي مسار متاح',
    vertPrefElevator: 'أفضل المصعد',
    vertPrefStairs: 'أفضل الدرج',
    floorTabPrefix: 'الطابق',
    continueTo: (label) => `المتابعة إلى الطابق ${label}`,
    reachedFloor: (label) => `وصلت إلى الطابق ${label}`,
    stepOf: (i, n) => `الخطوة ${i} من ${n}`,
    stepsRemaining: (n) => `${n} خطوات متبقية`,
    previousStep: 'السابق',
    reachedStep: 'وصلت — التالي',
    repeatStep: 'كرر التعليمات',
    remainingTime: 'المتبقي',
    remainingDistance: 'متبقٍ',
    progressHint: 'يتحدث التقدم عند تأكيد كل خطوة تنقل.',
    startLabel: 'نقطة البداية',
    currentFloorLabel: 'الطابق الحالي',
    destFloorLabel: 'طابق الوجهة',
    routePrefLabel: 'تفضيل المسار',
    totalTimeLabel: 'الوقت الإجمالي المقدر',
    totalDistanceLabel: 'المسافة الإجمالية',
    connectorElevator: 'مصعد',
    connectorStairs: 'درج',
    connectorEscalator: 'سلم متحرك',
    connectorRamp: 'منحدر',
    connectorGeneric: 'انتقال بين الطوابق',
    estimatedTransitionTime: 'الوقت المقدر',
    elapsedTime: 'الوقت المنقضي',
    estimatedJourneyTime: 'الوقت الإجمالي المقدر للرحلة',
    estimatedSteps: (n) => `~${n} خطوة (تقديري)`,
  },
  he: {
    back:        'חזרה',
    optionCode:   'הזנת קוד חדר',
    optionScan:   'סריקת קוד QR',
    verify:       'אימות',
    confirmTitle: 'אימות או עדכון המיקום שלך',
    confirmHint:  'הזן קוד חדר או סרוק את ה-QR שלו כדי לאשר היכן אתה. אם אתה במקום אחר, המסלול יחושב מחדש משם.',
    goingTo:      'היעד',
    scanQr:       'סריקת QR',
    rescanCtaHint: 'הזן קוד חדר או סרוק QR כדי לעדכן את מיקומך',
    scanTitle:    'סרוק את קוד ה-QR של החדר',
    scanHint:     'כוון את המצלמה לקוד QuickRoute שעל הדלת או הקיר.',
    scanStarting: 'מפעיל מצלמה...',
    scanDenied:   'הגישה למצלמה נחסמה.',
    scanUnavailable: 'לא ניתן היה להפעיל את המצלמה.',
    scanUnsupported: 'הדפדפן הזה אינו תומך בשימוש במצלמה.',
    scanErrorHint: 'עדיין אפשר להזין את הקוד ידנית.',
    destination: 'היעד שלך',
    routeReady:  'מסלול מוכן',
    navigating:  'מנווט',
    arrived:     'הגעת',
    startNav:    'התחל ניווט',
    exitNav:     'צא מהניווט',
    endNav:      'סיים ניווט',
    you:         'אתה',
    directions:  'הוראות',
    navHint:     'הקש ✓ בכל שלב שהשלמת',
    arrivedTitle:'הגעת ליעד',
    rescanCta:    'עדכון המיקום הנוכחי שלי',
    rescanTitle: 'סרוק או הזן קוד חדר',
    rescanHint:  'המסלול יחושב מחדש מהמיקום הנוכחי שלך',
    rescanPlaceholder: 'קוד חדר',
    rescanSubmit:'עדכן את מיקומי',
    rescanCancel:'ביטול',
    rescanSame:  'אתה כבר נמצא במיקום הזה',
    rescanInvalid:'לא נמצא קוד כזה',
    rescanOtherBuilding:'הקוד הזה שייך לבניין אחר',
    relocatedTo: (label) => `המיקום עודכן: ${label}`,
    arrivedSub:  'הגעת ליעדך',
    loadingRoute:'מכין את המסלול...',
    noRoute:     'לא נמצא מסלול זמין',
    noRouteHint: 'היעד הזה עדיין לא חובר לרשת הניווט',
    noStartPoint:'עדיין לא הוגדרה נקודת כניסה לבניין הזה',
    toLabel:     'אל',
    nextLabel:   'הבא',
    youAreNowOnFloor: (label) => `כעת אתה ב${label}`,
    stopNav:     'עצירת ניווט',
    floorsLabel: (n) => `${n} קומות`,
    accessibleYes: 'נגיש לכיסא גלגלים',
    accessibleNo:  'לא נגיש במלואו',
    modeShortest: 'הקצר ביותר',
    modeFastest:  'המהיר ביותר',
    modeAccessible: 'נגיש',
    vertPrefAny: 'כל מסלול זמין',
    vertPrefElevator: 'העדפת מעלית',
    vertPrefStairs: 'העדפת מדרגות',
    floorTabPrefix: 'קומה',
    continueTo: (label) => `המשך לקומה ${label}`,
    reachedFloor: (label) => `הגעתי לקומה ${label}`,
    stepOf: (i, n) => `שלב ${i} מתוך ${n}`,
    stepsRemaining: (n) => `${n} שלבים נותרו`,
    previousStep: 'הקודם',
    reachedStep: 'הגעתי — הבא',
    repeatStep: 'חזור על ההוראה',
    remainingTime: 'נותר',
    remainingDistance: 'נותרו',
    progressHint: 'ההתקדמות מתעדכנת כשאתה מאשר כל שלב ניווט.',
    startLabel: 'נקודת התחלה',
    currentFloorLabel: 'קומה נוכחית',
    destFloorLabel: 'קומת היעד',
    routePrefLabel: 'העדפת מסלול',
    totalTimeLabel: 'זמן כולל משוער',
    totalDistanceLabel: 'מרחק כולל',
    connectorElevator: 'מעלית',
    connectorStairs: 'מדרגות',
    connectorEscalator: 'מדרגות נעות',
    connectorRamp: 'רמפה',
    connectorGeneric: 'מעבר בין קומות',
    estimatedTransitionTime: 'זמן משוער',
    elapsedTime: 'זמן שחלף',
    estimatedJourneyTime: 'זמן נסיעה משוער',
    estimatedSteps: (n) => `~${n} צעדים (הערכה)`,
  },
};

// ── Icons ─────────────────────────────────────────────────────────────────────
// Note: the old ClockIcon/WalkIcon/FootstepsIcon (used for the now-removed
// distance/ETA/estimated-steps stats — Section 3) were removed here since
// they became fully unused. The pure calculations they used to sit next to
// (formatDistance/formatTime/estimateSteps in utils/routeHelpers.js) were
// NOT touched — see the file-level comment near the top.

const NavArrow = ({ flip }) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const BigCheckIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="11" fill="rgba(39,174,96,0.15)" stroke="#27ae60" strokeWidth="1.5"/>
    <path d="M7 12l4 4 6-7" stroke="#27ae60" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// Header "stop navigation" icon (Section A — accessible exit/stop button).
const StopIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
    <rect x="5" y="5" width="14" height="14" rx="2.5" stroke="currentColor" strokeWidth="2" />
  </svg>
);

// The control this sits on calls handleRepeatStep, which speaks the
// current instruction aloud through window.speechSynthesis. It used to
// carry a circular two-arrow glyph, which reads as "restart / go back to
// the beginning" — the one thing it does not do, and an alarming thing to
// offer someone halfway along a route. A speaker is what the button
// actually is. The BEHAVIOUR is unchanged; only the glyph moved.
const SpeakIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
    <path d="M11 5L6.5 8.5H3.5v7h3L11 19V5z" stroke="currentColor" strokeWidth="1.9"
      strokeLinejoin="round" fill="none"/>
    <path d="M15.5 9.2a4 4 0 0 1 0 5.6M18.2 6.5a7.8 7.8 0 0 1 0 11"
      stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
  </svg>
);

// Scanning — a QR frame with a sweep line.
const ScanIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M4 8.5V6a2 2 0 0 1 2-2h2.5M15.5 4H18a2 2 0 0 1 2 2v2.5M20 15.5V18a2 2 0 0 1-2 2h-2.5M8.5 20H6a2 2 0 0 1-2-2v-2.5"
      stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
    <path d="M3.5 12h17" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
  </svg>
);

// Current position — a map pin.
const PinIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z"
      stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" fill="none"/>
    <circle cx="12" cy="10" r="2.6" stroke="currentColor" strokeWidth="1.9" fill="none"/>
  </svg>
);

// The destination — a navigation arrow.
const FloorLayersIcon = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 3l8.5 4.5L12 12 3.5 7.5 12 3z"
      stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" fill="none"/>
    <path d="M3.5 12.4L12 16.9l8.5-4.5M3.5 16.9L12 21.4l8.5-4.5"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const NavIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M21 3L10.5 21l-2-8.5L0 10.5 21 3z" transform="translate(1.5 0)"
      stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" fill="none"/>
  </svg>
);

// Directional chevrons. `isRTL` mirrors them so "previous" always points
// back the way the reader came, in every language.
const ChevronBackIcon = ({ isRTL }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"
    style={isRTL ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M15 5l-7 7 7 7" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronNextIcon = ({ isRTL }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"
    style={isRTL ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M9 5l7 7-7 7" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const CheckIcon = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M20 6L9 17l-5-5" stroke="currentColor" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ElevatorIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <rect x="5" y="3" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M9 10l3-3 3 3M9 14l3 3 3-3" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const StairsIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path d="M3 21h4v-4h4v-4h4V9h4V5" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M3 21V17M7 17v-4M11 13V9M15 9V5M19 5v16" stroke="currentColor"
      strokeWidth="1.4" strokeLinecap="round" opacity="0.5"/>
  </svg>
);

const EscalatorIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path d="M4 19h4l10-12h2" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
    <circle cx="6" cy="19" r="1.6" fill="currentColor"/>
    <circle cx="18" cy="7" r="1.6" fill="currentColor"/>
    <path d="M4 15h3M9 15h2M13 11h2M17 11h2" stroke="currentColor" strokeWidth="1.3"
      strokeLinecap="round" opacity="0.5"/>
  </svg>
);

const RampIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path d="M3 19h6l12-12" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M3 19V21H21" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" opacity="0.5"/>
  </svg>
);

const ConnectorIcon = ({ type }) => {
  if (type === 'stairs') return <StairsIcon />;
  if (type === 'escalator') return <EscalatorIcon />;
  if (type === 'ramp') return <RampIcon />;
  return <ElevatorIcon />;
};

// ── Big direction arrow — Part 2.C: physical left/right must remain
// physically correct regardless of RTL text direction, so this
// deliberately ignores `isRTL` — a physical-left arrow always points to
// the reader's actual left, never mirrored just because the page is RTL.
const DIRECTION_ROTATION = {
  start: 0,
  straight: 0,
  slight_right: 30,
  right: 90,
  sharp_right: 135,
  u_turn: 180,
  sharp_left: -135,
  left: -90,
  slight_left: -30,
};

const BigDirectionArrow = ({ direction, size = 56 }) => {
  const rotation = DIRECTION_ROTATION[direction] ?? 0;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      style={{ transform: `rotate(${rotation}deg)`, transition: 'transform 0.25s ease' }}
    >
      <path
        d="M12 20V4M12 4l-6 6M12 4l6 6"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};


// ── Screen ────────────────────────────────────────────────────────────────────
// This screen deliberately has NO architectural floor-plan image, route
// polyline, markers, or zoom/pan map controls — end-user navigation is
// entirely text/instruction-based (destination name, current floor,
// current + next instruction with a direction icon, "Step X of Y",
// Previous/Next controls, explicit floor-transition cards, arrival state).
// A prior revision briefly reintroduced a redesigned map component
// (components/NavigationRouteMap.jsx) here; that decision is reversed
// again by this task because map images have proven unreliable for
// end users. NavigationRouteMap.jsx itself is left in place unmodified
// (not deleted) in case it's used elsewhere later; it is simply never
// rendered by this screen. Nothing about the underlying route data
// changes — map ids, floor segments, route coordinates, and backend
// distance/time calculations are still fully computed and available in
// state, just never shown as a map image here. Admin map/graph editing
// and calibration remain exclusively in screens/AdminMapScreen.jsx,
// which this screen never touches.
const IndoorNavigationScreen = () => {
  const { lang, setLang } = useLang();
  const navigate  = useNavigate();
  const location  = useLocation();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const building = location.state?.building    ?? null;
  const room     = location.state?.destination ?? location.state?.room ?? null;

  // Re-resolved from the raw `names`/`nameEn` carried on the navigation
  // state whenever `lang` changes — so switching language while already
  // on this screen (via the language switcher) immediately updates the
  // arrival/current-location text, with no re-fetch, no MongoDB write,
  // and no re-running of the semantic analysis (Section 9). Falls back
  // to whatever `.name` was already resolved at navigation time for a
  // destination that predates this field (e.g. still holds only a plain
  // legacy string).
  const roomDisplayName = useMemo(
    () => (room ? getLocalizedText(room.names, lang, room.nameEn || room.name) : ''),
    [room, lang],
  );
  const buildingDisplayName = useMemo(
    () => (building ? getLocalizedText(building.names, lang, building.nameEn || building.name) : ''),
    [building, lang],
  );

  // Navigation (walkthrough) state
  const [isNavigating, setIsNavigating] = useState(false);
  // Completed step indices, PER FLOOR (PHASE 13: instructions are shown
  // and tracked floor-by-floor, not as one flat cross-floor list).
  const [completedByFloor, setCompletedByFloor] = useState({});
  const [activeFloorIndex, setActiveFloorIndex] = useState(0);

  // Real starting-location label — from a resolved Location Code when
  // available, otherwise the entrance RoutePoint's own name. Never
  // fabricated; "—" is shown when neither is available.
  //
  // Split into two pieces of state so a language switch can instantly
  // re-render this label with zero refetch/MongoDB write (Section 9):
  // `startLabelFromCode` is the QR/Location-Code flow's own already-
  // resolved, language-independent legacy string (out of scope for this
  // task — see BarcodeEntryScreen.jsx), while `startRoutePoint` is the raw
  // RoutePoint record (with its existing display_name_en/ar/he fields)
  // used for the entrance-fallback case, resolved to the current `lang`
  // just below via useMemo.
  const [startLabelFromCode, setStartLabelFromCode] = useState(null);
  const [startRoutePoint, setStartRoutePoint] = useState(null);

  // Mid-journey relocation / arrival confirmation by room QR.
  //
  // `relocatePointId` is a plain id string, NOT the point object, on
  // purpose: it goes into the route effect's dependency array below, and an
  // object would be a new reference on every render and re-request the
  // route forever. When set it wins over the persisted
  // quickroute_start_location, so "recalculate from where I am now" needs
  // no new navigation architecture — the existing effect simply resolves a
  // different start. routeStateKey already includes start_point_id, so the
  // per-floor step progress resets itself for the new route with no extra
  // code (see the restore/reset effect further down).
  const [relocatePointId, setRelocatePointId] = useState(null);
  // The destination's arrival RoutePoint id. Derived once at component
  // scope (it used to be a local inside the route effect) because the
  // rescan handler needs the same value to decide "is this scanned code my
  // destination?" for legacy points that carry no room_id.
  const destinationRoutePointId = useMemo(
    () => getDestinationRoutePointId(room),
    [room],
  );
  // Set only when the user scans the QR of the room they are navigating TO.
  // This is the authoritative, position-based arrival signal; the existing
  // "every step ticked" signal is kept as-is and either one is enough.
  const [scanArrived, setScanArrived] = useState(false);
  const [scanCode, setScanCode] = useState('');
  const [scanBusy, setScanBusy] = useState(false);
  const [scanError, setScanError] = useState(null);
  const [scanNotice, setScanNotice] = useState(null);
  // Camera overlay visibility. Purely presentational: the scanner reads a
  // string and hands it to applyLocationCode below.
  const [scannerOpen, setScannerOpen] = useState(false);
  const startLabel = useMemo(() => {
    if (startLabelFromCode) return startLabelFromCode;
    if (!startRoutePoint) return null;

    return (
      getLocalizedText(
        {
          en: startRoutePoint.display_name_en,
          ar: startRoutePoint.display_name_ar,
          he: startRoutePoint.display_name_he,
        },
        lang,
        startRoutePoint.display_name || startRoutePoint.name || '',
      ) || null
    );
  }, [startLabelFromCode, startRoutePoint, lang]);

  // PHASE 14 — route preferences.
  //
  // The route STRATEGY is unchanged and still sent on every request; only
  // its Shortest/Fastest/Accessible picker was removed from this screen.
  // 'shortest' was already the default every user started on, so the
  // request this screen makes is byte-identical to the one it made
  // before — the backend's optimization_mode handling, and the other
  // callers that still choose a mode, are untouched.
  const [optimizationMode] = useState('shortest');
  // Section 7 — single-choice vertical-transport preference: 'any' |
  // 'elevator' | 'stairs'. Sent as the new vertical_transport_preference
  // request field (backend/routes/navigation_routes.py); replaces the old
  // avoidStairs/avoidEscalators/preferElevators checkbox row on THIS
  // screen only — the backend still accepts those three booleans
  // unchanged for any other/older caller. Persisted only for the current
  // navigation flow (component state, not localStorage/sessionStorage).
  const [verticalPreference, setVerticalPreference] = useState('any');

  const [routeResult, setRouteResult] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeError, setRouteError] = useState('');

  // Elapsed-journey tracking — real timestamps only, never simulated.
  const [navStartedAt, setNavStartedAt] = useState(null);
  const [arrivedAt, setArrivedAt] = useState(null);

  // 1. Resolve real start/end route points (regardless of which floor
  //    either one is on) and call the real multi-floor navigation API.
  //    No local/fake route is ever calculated.
  useEffect(() => {
    if (!building?.id) return undefined;
    if (!room?.id) return undefined;

    let cancelled = false;

    const loadRoute = async () => {
      setRouteLoading(true);
      setRouteError('');
      setRouteResult(null);

      try {
        let startPoint = null;

        // Prefer a start point resolved from a scanned/typed location
        // code — used regardless of which floor it is on, since routing
        // is no longer restricted to a single map.
        let resolvedStart = null;
        try {
          const raw = localStorage.getItem(START_LOCATION_KEY);
          resolvedStart = raw ? JSON.parse(raw) : null;
        } catch {
          resolvedStart = null;
        }

        // A code scanned DURING this journey is the freshest truth about
        // where the user is, so it outranks the persisted start.
        const preferredStartPointId = relocatePointId || resolvedStart?.routePointId;

        if (preferredStartPointId) {
          try {
            const point = await getPublicRoutePointById(preferredStartPointId);
            if (point) startPoint = point;
          } catch (lookupErr) {
            console.warn('Resolved start point lookup failed:', lookupErr);
          }
        }

        if (!startPoint) {
          // Fall back to an entrance point actually scoped to the
          // SELECTED building — never an arbitrary "current map"'s
          // entrance, which could belong to a different building
          // entirely (QuickRoute UX Final Cleanup, Part 3/7).
          const entrancePoints = await getPublicRoutePoints({
            buildingId: building.id,
            pointType: 'entrance',
          });

          startPoint = Array.isArray(entrancePoints) ? entrancePoints[0] : null;
        }

        if (!startPoint) {
          if (!cancelled) {
            setRouteError(t.noStartPoint);
            setStartLabelFromCode(null);
            setStartRoutePoint(null);
          }
          return;
        }

        if (!cancelled) {
          // startPoint.name is the internal/technical, language-independent
          // RoutePoint identifier (e.g. set via Draw Walkable Path) — never
          // itself user-facing. The raw point (including its existing flat
          // display_name_en/ar/he fields) is stored as-is; `startLabel`
          // above resolves it to the current `lang` and re-resolves
          // instantly on every language change.
          // After a mid-journey rescan the persisted label belongs to the
          // PREVIOUS location, so it must not be reused — `startLabel`
          // falls back to the new point's own localized display name.
          setStartLabelFromCode(relocatePointId ? null : resolvedStart?.label || null);
          setStartRoutePoint(startPoint);
        }

        // Resolve the destination's RoutePoint directly from the id the
        // backend stored on the Room when it was placed on the map — never
        // falls back to a nearest/arbitrary guess.

        if (!destinationRoutePointId) {
          if (!cancelled) setRouteError(t.noRoute);
          return;
        }

        let endPoint = null;
        try {
          endPoint = await getPublicRoutePointById(destinationRoutePointId);
        } catch (lookupErr) {
          console.warn('Destination route point lookup failed:', lookupErr);
        }

        if (!endPoint) {
          if (!cancelled) setRouteError(t.noRoute);
          return;
        }

        // `lang` drives the backend's already-existing localized instruction
        // TEXT (instruction_generator.py's TEXT_TEMPLATES) — never the
        // route/Dijkstra computation itself, which stays entirely
        // language-independent. Reusing this existing request field is the
        // whole mechanism behind Arabic/Hebrew turn-by-turn instructions
        // and landmark names (Sections 4/5/10) — no frontend recalculation.
        const result = await calculateMultiFloorRoute({
          startPointId: startPoint.id,
          endPointId: endPoint.id,
          optimizationMode,
          verticalTransportPreference: verticalPreference,
          lang,
        });

        if (!cancelled) setRouteResult(result);
      } catch (err) {
        console.error('Failed to calculate route:', err);
        // The backend's exact detail text (e.g. "No accessible route is
        // currently configured." or "No configured route between Floor 0
        // and Floor 3. Add or activate stairs/elevator connections.") is
        // shown verbatim — never replaced with a generic message, and
        // never silently substituted with an inaccessible fallback route.
        if (!cancelled) setRouteError(err.message || t.noRoute);
      } finally {
        if (!cancelled) setRouteLoading(false);
      }
    };

    loadRoute();

    return () => {
      cancelled = true;
    };
    // `lang` is intentionally included so switching the UI language
    // re-requests real, backend-generated instruction text in that
    // language (never invented client-side) — see the lang comment above
    // calculateMultiFloorRoute() just above.
    // `relocatePointId` is in this list so scanning another room's QR
    // mid-journey recalculates from there to the SAME destination — the
    // one behaviour change this feature needs from the routing effect. It
    // is deliberately the point ID (a string), not the point object, so it
    // is stable across renders and cannot re-trigger this effect forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    building?.id,
    room?.id,
    relocatePointId,
    destinationRoutePointId,
    optimizationMode,
    verticalPreference,
    lang,
  ]);

  const floorSegments = useMemo(
    () => getFloorSegments(routeResult?.segments),
    [routeResult],
  );
  const transitionSegments = useMemo(
    () => getTransitionSegments(routeResult?.segments),
    [routeResult],
  );
  const transitionInstructions = useMemo(
    () => getTransitionInstructions(routeResult?.instructions),
    [routeResult],
  );
  const instructionGroups = useMemo(
    () => groupInstructionsByFloor(routeResult?.instructions),
    [routeResult],
  );

  const routeStateKey = routeResult
    ? buildRouteStateKey({
        startPointId: routeResult.start_point_id,
        endPointId: routeResult.destination_point_id,
        optimizationMode: routeResult.optimization_mode,
        // Not echoed back on the response, so read from the live request
        // state directly — still correct because routeResult is nulled
        // out for the whole duration of any in-flight request (Section
        // 11: "never show previous ... route while waiting"), so this key
        // and routeResult always describe the same completed request.
        verticalPreference,
      })
    : null;

  // 2. Restore or reset per-route navigation progress whenever a NEW route
  //    result arrives (PHASE 13 requirement #10 — safe refresh recovery).
  useEffect(() => {
    if (!routeStateKey || floorSegments.length === 0) return;

    let restored = null;
    try {
      const raw = sessionStorage.getItem(NAV_STATE_STORAGE_PREFIX + routeStateKey);
      restored = raw ? JSON.parse(raw) : null;
    } catch {
      restored = null;
    }

    if (restored && restored.floorCount === floorSegments.length) {
      setActiveFloorIndex(
        Math.min(Math.max(0, restored.activeFloorIndex || 0), floorSegments.length - 1),
      );
      const restoredMap = {};
      Object.entries(restored.completedByFloor || {}).forEach(([key, indices]) => {
        restoredMap[key] = new Set(indices);
      });
      setCompletedByFloor(restoredMap);
      setIsNavigating(Boolean(restored.isNavigating));
      setNavStartedAt(restored.isNavigating ? (restored.navStartedAt || Date.now()) : null);
    } else {
      setActiveFloorIndex(0);
      setCompletedByFloor({});
      setIsNavigating(false);
      setNavStartedAt(null);
      setArrivedAt(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeStateKey, floorSegments.length]);

  // 3. Persist navigation progress on every change (best-effort — never
  //    blocks the UI if storage is unavailable).
  useEffect(() => {
    if (!routeStateKey) return;

    const serializable = {};
    Object.entries(completedByFloor).forEach(([key, set]) => {
      serializable[key] = Array.from(set);
    });

    try {
      sessionStorage.setItem(
        NAV_STATE_STORAGE_PREFIX + routeStateKey,
        JSON.stringify({
          floorCount: floorSegments.length,
          activeFloorIndex,
          completedByFloor: serializable,
          isNavigating,
          navStartedAt,
        }),
      );
    } catch {
      // Storage unavailable/full — navigation still works, it just won't
      // survive a refresh this time.
    }
  }, [routeStateKey, floorSegments.length, activeFloorIndex, completedByFloor, isNavigating, navStartedAt]);

  const currentFloorSteps = useMemo(
    () => (instructionGroups[activeFloorIndex] || []).map(instructionToStep),
    [instructionGroups, activeFloorIndex],
  );

  const currentFloorCompleted = completedByFloor[activeFloorIndex] || new Set();
  const activeStep = currentFloorSteps.findIndex((_, i) => !currentFloorCompleted.has(i));
  const isLastFloor = activeFloorIndex === floorSegments.length - 1;
  const currentFloorDone = isFloorComplete(currentFloorSteps.length, currentFloorCompleted);
  // Two independent, equally valid arrival signals:
  //   scanArrived  — the user scanned the destination room's own QR. This
  //                  is position-based and does not require the walkthrough
  //                  to have been started or every step to be ticked.
  //   the original — every instruction on the last floor checked off.
  const steppedThroughToEnd =
    isNavigating && isLastFloor && currentFloorDone && currentFloorSteps.length > 0;
  const hasArrived = scanArrived || steppedThroughToEnd;

  // 4. Track the real moment of arrival once, so an honest elapsed time
  //    can be shown (Part 2.G) — never a simulated/estimated value.
  useEffect(() => {
    if (hasArrived && navStartedAt && !arrivedAt) {
      setArrivedAt(Date.now());
    }
  }, [hasArrived, navStartedAt, arrivedAt]);

  const currentTransitionInstruction = !isLastFloor
    ? transitionInstructions[activeFloorIndex]
    : null;
  const currentTransitionSegment = !isLastFloor
    ? transitionSegments[activeFloorIndex]
    : null;
  const nextFloorSegment = !isLastFloor ? floorSegments[activeFloorIndex + 1] : null;

  // Part 2.C/2.D — the single "current instruction" the primary card
  // shows. Falls back to the last step once every step on this floor is
  // complete (activeStep === -1) so the card never goes blank right
  // before the transition/arrival card takes over.
  const currentStepData = activeStep >= 0
    ? currentFloorSteps[activeStep]
    : currentFloorSteps[currentFloorSteps.length - 1];

  // Real backend values — kept exactly as returned and stored in state
  // (routeResult) untouched. This screen simply never renders them (Section
  // 3): the demo maps' calibration isn't trustworthy enough to present a
  // number that looks precise.
  const totalDistance = routeResult?.total_distance_meters ?? null;
  const totalTimeSeconds = routeResult?.total_estimated_time_seconds ?? null;

  const overallProgress = useMemo(
    () => computeOverallProgress({
      instructionGroups,
      completedByFloor,
      totalDistanceMeters: totalDistance,
      totalTimeSeconds,
    }),
    [instructionGroups, completedByFloor, totalDistance, totalTimeSeconds],
  );

  // Instruction-COUNT progress only (Section 4.D) — never metres/time.
  // overallProgress itself (utils/multiFloorRouteHelpers.js) also still
  // computes remainingDistanceMeters/remainingTimeSeconds from the real
  // backend totals for any future consumer; this screen just never reads
  // those two fields.
  const stepsRemaining = Math.max(0, overallProgress.totalSteps - overallProgress.completedSteps);
  const overallStepNumber = Math.min(overallProgress.completedSteps + 1, overallProgress.totalSteps || 1);

  // Section 4.C — the single next meaningful instruction, crossing the
  // floor boundary into the transition instruction when this floor's
  // steps are exhausted. Pure display selection over the exact same
  // backend-ordered data as the current-instruction card; never reorders,
  // skips, or invents a step.
  const nextInstructionStep = getNextMeaningfulInstruction({
    currentFloorSteps,
    activeStep,
    isLastFloor,
    transitionInstructions,
    activeFloorIndex,
  });

  const handleStepToggle = (index) => {
    setCompletedByFloor((prev) => {
      const nextSet = new Set(prev[activeFloorIndex] || []);
      if (nextSet.has(index)) nextSet.delete(index);
      else nextSet.add(index);
      return { ...prev, [activeFloorIndex]: nextSet };
    });
  };

  // "Reached — Next": confirms the currently-active step. "Previous":
  // un-confirms the immediately-preceding step. Both operate ONLY on the
  // active floor's own step indices — never reach across floors, matching
  // how completedByFloor is already partitioned everywhere else.
  const handleReachedStep = () => {
    if (activeStep < 0) return;
    handleStepToggle(activeStep);
  };

  const previousStepIndex = (activeStep < 0 ? currentFloorSteps.length : activeStep) - 1;
  const canGoToPreviousStep = previousStepIndex >= 0 && currentFloorCompleted.has(previousStepIndex);

  const handlePreviousStep = () => {
    if (!canGoToPreviousStep) return;
    handleStepToggle(previousStepIndex);
  };

  // Section 4.F — floor changes appear as explicit navigation steps, and a
  // confirmation message appears after the floor switch. `floorConfirmation`
  // is transient (auto-clears below) and purely presentational — it never
  // affects routing/progress state.
  const [floorConfirmation, setFloorConfirmation] = useState(null);

  const handleAdvanceFloor = () => {
    if (isLastFloor) return;
    const newIndex = Math.min(activeFloorIndex + 1, floorSegments.length - 1);
    const newSegment = floorSegments[newIndex];
    setActiveFloorIndex(newIndex);
    if (newSegment) {
      const label = newSegment.floor_label || `${t.floorTabPrefix} ${newSegment.floor}`;
      setFloorConfirmation(t.youAreNowOnFloor(label));
    }
  };

  useEffect(() => {
    if (!floorConfirmation) return undefined;
    const timer = setTimeout(() => setFloorConfirmation(null), 4000);
    return () => clearTimeout(timer);
  }, [floorConfirmation]);

  // "Repeat instruction" — reads the current instruction aloud using the
  // browser's built-in speech synthesis when the browser actually
  // supports it (Part 2.E: "if currently supported"). A silent no-op
  // otherwise; never a fake/simulated repeat.
  const handleRepeatStep = () => {
    if (!currentStepData?.text) return;
    if (typeof window === 'undefined') return;
    if (!window.speechSynthesis || typeof window.SpeechSynthesisUtterance !== 'function') return;

    try {
      window.speechSynthesis.cancel();
      const utterance = new window.SpeechSynthesisUtterance(currentStepData.text);
      utterance.lang = lang === 'ar' ? 'ar-SA' : lang === 'he' ? 'he-IL' : 'en-US';
      window.speechSynthesis.speak(utterance);
    } catch (err) {
      console.warn('Speech synthesis unavailable:', err);
    }
  };

  const handleStartNav = () => {
    setIsNavigating(true);
    setActiveFloorIndex(0);
    setCompletedByFloor({});
    setNavStartedAt(Date.now());
    setArrivedAt(null);
  };

  const handleCancelNav = () => {
    setIsNavigating(false);
    setActiveFloorIndex(0);
    setCompletedByFloor({});
    setNavStartedAt(null);
    setArrivedAt(null);
    setScanArrived(false);
  };

  // ------------------------------------------------------------------
  // Scan a room QR mid-journey: relocate, or confirm arrival.
  //
  // The QR is only ever a location identifier. It is resolved to a
  // RoutePoint through the existing PUBLIC endpoints, and the decision of
  // what that means is a pure function (utils/locationScan.js) so it can be
  // unit tested without React. Nothing here touches the navigation graph:
  // recalculation is just the existing route effect running again with a
  // different start point.
  // ------------------------------------------------------------------
  //
  // applyLocationCode() is that single path. A typed code and a camera
  // scan both land here; the camera contributes nothing but the string it
  // read. There is exactly one resolveLocationCode call site for
  // relocation on this screen, and exactly one place that decides what a
  // resolved code means.
  const applyLocationCode = async (rawCode) => {
    const code = (rawCode ?? '').trim();
    if (!code || scanBusy) return;

    setScanBusy(true);
    setScanError(null);
    setScanNotice(null);

    try {
      const resolved = await resolveLocationCode(code);

      if (!isScanInActiveBuilding(resolved, building?.id)) {
        setScanError(t.rescanOtherBuilding);
        return;
      }

      const scannedPoint = await getPublicRoutePointById(resolved?.route_point_id);

      const { outcome, startPointId } = classifyScannedLocation({
        scannedPoint,
        destinationRoomId: room?.id ?? null,
        destinationRoutePointId,
        currentStartPointId: startRoutePoint?.id ?? null,
      });

      if (outcome === 'invalid') {
        setScanError(t.rescanInvalid);
        return;
      }

      // Persist the new position under the SAME key BarcodeEntryScreen
      // uses, so a reload mid-journey resumes from here rather than from
      // the original entrance.
      const record = buildStartLocationRecord(resolved);
      if (record) {
        try {
          localStorage.setItem(START_LOCATION_KEY, JSON.stringify(record));
        } catch {
          // A private-mode storage failure must never block navigation.
        }
      }

      if (outcome === 'arrived') {
        // Confirmed by position, not by ticking steps.
        setScanArrived(true);
        setScanCode('');
        return;
      }

      if (outcome === 'unchanged') {
        setScanNotice(t.rescanSame);
        return;
      }

      // outcome === 'relocate' — same destination, new starting point. The
      // route effect below re-runs because relocatePointId is one of its
      // dependencies, and routeStateKey changes so step progress resets.
      setScanArrived(false);
      setRelocatePointId(startPointId);
      setScanCode('');
      setScanNotice(t.relocatedTo(resolved?.label || code));
    } catch (err) {
      console.warn('Location code rescan failed:', err);
      setScanError(t.rescanInvalid);
    } finally {
      setScanBusy(false);
    }
  };

  const handleScanSubmit = (event) => {
    event?.preventDefault?.();
    applyLocationCode(scanCode);
  };

  // A camera result is just a string. QuickRoute QR labels encode a URL
  // (`…/?locationCode=CODE`), so the code is lifted out of it first — then
  // it goes through the identical resolver above. A scan of a code that is
  // NOT the destination is therefore a relocation, exactly as a typed one
  // is; only the backend resolver can call a code invalid.
  const handleScanResult = (text) => {
    setScannerOpen(false);

    const code = extractLocationCode(text);

    if (!code) {
      setScanError(t.rescanInvalid);
      return;
    }

    setScanCode(code);
    applyLocationCode(code);
  };

  // Arrival is no longer something the user can simply declare: it is
  // established only by the resolver recognising the scanned/typed code
  // AS the destination (outcome === 'arrived' above), or by stepping
  // through every instruction. Both paths are unchanged.

  const hasRealRoute = floorSegments.length > 0;

  // Badge config — Section 3: a truthful "route was computed" statement,
  // never a distance/ETA claim. `navigating`/`arrived` remain honest
  // navigation-PROGRESS labels (not accuracy claims), so those two states
  // are kept; only the pre-navigation wording changes to the exact
  // required phrase.
  // The route-calculated status badge was removed: visible directions
  // already tell the user a route exists, and the phrase read like an
  // accuracy claim. Its dictionary string was removed too; the arrived
  // and navigating labels remain for the other states that use them.

  // Section 7 — matches the backend's VERTICAL_PREFERENCE_VALUES exactly
  // ('any' | 'elevator' | 'stairs'); order here is the exact required
  // reading order ("Any available route / Prefer elevator / Prefer
  // stairs").
  const vertPrefOptions = [
    { value: 'any', label: t.vertPrefAny },
    { value: 'elevator', label: t.vertPrefElevator },
    { value: 'stairs', label: t.vertPrefStairs },
  ];

  // Real floor labels for the summary card, preferring each segment's own
  // backend floor_label (e.g. an admin-set "Ground Floor" or "Mezzanine")
  // and falling back to the compact formatFloor() code. Never invented:
  // when no route has been computed the value is null and the card shows
  // a dash rather than a guess.
  const startFloorLabel = floorSegments[0]
    ? (floorSegments[0].floor_label || formatFloor(floorSegments[0].floor))
    : null;
  const lastFloorSegment = floorSegments[floorSegments.length - 1] || null;
  const destFloorLabel = lastFloorSegment
    ? (lastFloorSegment.floor_label || formatFloor(lastFloorSegment.floor))
    : (room ? formatFloor(room.floor) : null);

  return (
    <div className="layout-wrapper">
      <div className="layout-shell s18-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Compact header — no architectural map behind it, ever ── */}
        <div className="s18-header">
          <div className="s18-header-top">
            <BackButton
              onClick={() => navigate(ROUTES.destinations, { state: { building } })}
              label={t.back}
              isRTL={isRTL}
              spacing="compact"
            />

            {/* Section A — accessible button to exit/stop navigation,
                always reachable from the header regardless of scroll
                position. Only shown while actively navigating; before
                Start Navigation the Back button above already serves as
                the exit action. */}
            {isNavigating && !hasArrived && (
              <button
                type="button"
                className="s18-stop-nav-btn"
                onClick={handleCancelNav}
                aria-label={t.stopNav}
                title={t.stopNav}
              >
                <StopIcon />
              </button>
            )}

            <div className="s18-lang-pill" role="group" aria-label="Language selector">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  className={`s18-lang-btn${lang === l.code ? ' active' : ''}`}
                  onClick={() => setLang(l.code)}
                  aria-pressed={lang === l.code}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          <div className="s18-brand-row">
            <div className="s18-logo-card">
              <QuickRouteLogo size={18} />
            </div>
            <span className="s18-wordmark">
              Quick<span>Route</span>
            </span>
          </div>

          {/* Building context only. The destination used to be repeated
              here as well, immediately above the hero that states it in
              full — one of the "fragmented and text-heavy" repetitions
              this pass removes. */}
          {building && (
            <div className="s18-header-info">
              <span className="s18-header-building">{buildingDisplayName}</span>
            </div>
          )}

          {/* ── Section A: Destination header — destination name, its
              floor, and a truthful "shortest route calculated" status
              badge (never a distance/ETA claim). ── */}
          {room && (
            <div className="s18-nav-destination">
              <span className="s18-nav-dest-icon" aria-hidden="true">
                <NavIcon size={22} />
              </span>
              <p className="s18-nav-dest-label">{t.goingTo}</p>
              <h1 className="s18-nav-dest-name">{roomDisplayName}</h1>
              {startLabel && (
                <p className="s18-nav-dest-from">
                  <PinIcon size={13} />
                  <span>{t.startLabel}: {startLabel}</span>
                </p>
              )}
            </div>
          )}
        </div>

        {/* Section 4.F — transient confirmation after a floor switch */}
        {floorConfirmation && (
          <div className="s18-floor-confirm" role="status">
            {floorConfirmation}
          </div>
        )}

        {/* ── Floor stepper — PHASE 13 requirement #3 ── */}
        {floorSegments.length > 1 && (
          <div className="s18-floor-stepper" role="tablist">
            {floorSegments.map((segment, index) => (
              <button
                key={segment.map_id || index}
                type="button"
                role="tab"
                aria-selected={index === activeFloorIndex}
                className={`s18-floor-tab${index === activeFloorIndex ? ' s18-floor-tab--active' : ''}`}
                onClick={() => setActiveFloorIndex(index)}
              >
                {segment.floor_label || `${t.floorTabPrefix} ${segment.floor}`}
              </button>
            ))}
          </div>
        )}

        {/* ── Scrollable bottom ── */}
        <div className="s18-bottom">

          {/* Section 4.G — Arrival state. Replaces the normal
              instruction card entirely once the final instruction is
              reached. Deliberately shows NO distance/ETA (Section 3/4.G):
              just the destination name and its floor, plus the single End
              Navigation action at the bottom of this screen. */}
          {hasArrived && (
            <div className="s18-arrival s18-arrival--compact">
              <BigCheckIcon />
              <div className="s18-arrival-text">
                <p className="s18-arrival-title">{t.arrivedTitle}</p>
                <p className="s18-arrival-sub">{room ? roomDisplayName : t.arrivedSub}</p>
              </div>
            </div>
          )}

          {/* Route summary — four real values, or a dash. Every one
              comes from the resolved start, the selected destination or
              the backend's own floor segments; none is invented, and a
              missing value degrades to "—" rather than to a guess. */}
          <div className="s18-summary-card">
            <div className="s18-summary-item">
              <span className="s18-summary-head">
                <PinIcon size={13} />
                <span className="s18-summary-label">{t.startLabel}</span>
              </span>
              <span className="s18-summary-value">{startLabel || '—'}</span>
            </div>

            <div className="s18-summary-item">
              <span className="s18-summary-head">
                <NavIcon size={13} />
                <span className="s18-summary-label">{t.destination}</span>
              </span>
              <span className="s18-summary-value">
                {room ? roomDisplayName : building ? buildingDisplayName : '—'}
              </span>
            </div>

            <div className="s18-summary-item">
              <span className="s18-summary-head">
                <FloorLayersIcon size={13} />
                <span className="s18-summary-label">{t.currentFloorLabel}</span>
              </span>
              <span className="s18-summary-value">{startFloorLabel || '—'}</span>
            </div>

            <div className="s18-summary-item">
              <span className="s18-summary-head">
                <FloorLayersIcon size={13} />
                <span className="s18-summary-label">{t.destFloorLabel}</span>
              </span>
              <span className="s18-summary-value">{destFloorLabel || '—'}</span>
            </div>
          </div>

          {/* PHASE 14 — route preferences */}
          {room?.id && (
            <div className="s18-mode-card">
              {/* Section 7 — single-choice vertical-transport preference
                  segmented control (replaces the old avoid-stairs/
                  avoid-escalators/prefer-elevators checkbox row on this
                  screen). Applied as a per-request graph-edge filter on
                  the backend (Section 8), never a permanent change to
                  connector data. Changing it re-requests the route for
                  the SAME start/destination (Section 11) — the request-
                  loading effect above already depends on
                  `verticalPreference`. */}
              <div className="s18-vertpref-row" role="radiogroup" aria-label={t.vertPrefAny}>
                {vertPrefOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={verticalPreference === option.value}
                    className={`s18-vertpref-btn${verticalPreference === option.value ? ' s18-vertpref-btn--active' : ''}`}
                    onClick={() => setVerticalPreference(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Route status / empty states — never a fake fallback route */}
          {routeLoading && (
            <div className="s18-info-card">
              <p>{t.loadingRoute}</p>
            </div>
          )}

          {!routeLoading && routeError && (
            <div className="s18-info-card">
              <p>{routeError}</p>
              <p className="s18-dest-meta" style={{ marginTop: 6 }}>{t.noRouteHint}</p>
            </div>
          )}

          {/* ── Section B: Primary current-instruction card — the single
              most important element on the screen. Large direction arrow +
              one clear instruction (distance-free display text — Section
              3/7), cross-floor "Step X of Y" (Section 4.D — instruction
              count only, never metres), an instruction-sequence progress
              bar, and Previous / Reached-Next / Repeat controls. Never a
              simulated live position — progress only ever moves when the
              user explicitly confirms a step. */}
          {!routeLoading && !routeError && isNavigating && !hasArrived && currentStepData && (
            <div className="s18-current-card">
              <div className="s18-current-body">
                {/* The large circular illustration that used to sit above
                    this was decoration, not information — it told the user
                    nothing the instruction text does not. What remains is
                    the SAME icon from the same route-instruction system,
                    at inline size beside the step counter, where it reads
                    as a movement cue rather than artwork. */}
                <p className="s18-current-step-of">
                  <span className="s18-current-step-icon" aria-hidden="true">
                    {currentStepData.type === 'exit'
                      ? <NavArrow flip={isRTL} />
                      : currentStepData.type === 'arrive'
                        ? <BigCheckIcon />
                        : <BigDirectionArrow direction={currentStepData.direction} size={16} />}
                  </span>
                  <span>{t.stepOf(overallStepNumber, overallProgress.totalSteps)}</span>
                </p>
                <p className="s18-current-text">{currentStepData.text}</p>

                {/* ── Section C: Next-instruction preview — secondary,
                    smaller, only the single next meaningful instruction. */}
                {nextInstructionStep && (
                  <p className="s18-next-preview">
                    <span className="s18-next-preview-label">{t.nextLabel}:</span>{' '}
                    <span className="s18-next-preview-text">{nextInstructionStep.text}</span>
                  </p>
                )}
              </div>

              {/* ── Section D: Route progress — instruction-sequence only. */}
              <div className="s18-current-progress">
                <div className="s18-progress-row">
                  <div className="s18-progress-track">
                    <div
                      className="s18-progress-fill"
                      style={{ width: `${Math.round(overallProgress.progressFraction * 100)}%` }}
                    />
                  </div>
                  <span className="s18-progress-pct">
                    {Math.round(overallProgress.progressFraction * 100)}%
                  </span>
                </div>
                <p className="s18-steps-remaining">{t.stepsRemaining(stepsRemaining)}</p>
              </div>

              <div className="s18-current-controls">
                <button
                  type="button"
                  className="s18-current-btn s18-current-btn--secondary"
                  onClick={handlePreviousStep}
                  disabled={!canGoToPreviousStep}
                >
                  <ChevronBackIcon isRTL={isRTL} />
                  <span>{t.previousStep}</span>
                </button>
                <button
                  type="button"
                  className="s18-repeat-btn"
                  onClick={handleRepeatStep}
                  aria-label={t.repeatStep}
                  title={t.repeatStep}
                >
                  <SpeakIcon />
                </button>
                <button
                  type="button"
                  className="s18-current-btn s18-current-btn--primary"
                  onClick={handleReachedStep}
                >
                  <span>{t.reachedStep}</span>
                  <ChevronNextIcon isRTL={isRTL} />
                </button>
              </div>
            </div>
          )}

          {/* Section E ("route map") deliberately removed again — this
              task's Section 2 explicitly reverses the prior revision's
              decision to reintroduce the architectural map on the
              END-USER navigation screen (map images are unreliable per
              the reported problem). NavigationRouteMap.jsx itself is left
              in place unmodified (still importable elsewhere / by admin
              screens); only its use HERE is removed. Nothing about the
              route data itself changes: floorSegments, coordinates, map
              ids, and distances/times are still fully computed and held
              in state, just never rendered as a map image. */}

          {/* Directions section — built only from the real returned path,
              scoped to the ACTIVE floor only (PHASE 13). Acts as the
              full checklist behind the primary current-instruction card
              above (and as the pre-navigation preview before Start). */}
          {!routeLoading && !routeError && currentFloorSteps.length > 0 && (
            <div className="s18-directions">
              <div className="s18-directions-header">
                <p className="s18-directions-label">{t.directions}</p>
                {isNavigating && !hasArrived && (
                  <p className="s18-nav-hint">{t.navHint}</p>
                )}
              </div>
              <RouteSteps
                outdoorSteps={[]}
                indoorSteps={currentFloorSteps}
                lang={lang}
                isNavigating={isNavigating}
                completedSteps={currentFloorCompleted}
                activeStep={activeStep}
                onStepToggle={handleStepToggle}
              />
            </div>
          )}

          {/* Floor transition card — Part 2.F: real connector data
              straight from the backend's segment response (connector
              name/type, from/to floor, accessibility, estimated time),
              with the confirmation that auto-advances the floor
              stepper. */}
          {/* Floor change — a compact inline bar, not the large card
              this used to be. The connector's own floor/accessibility/
              estimated-time metadata rows were removed as clutter; the
              REAL transition instruction text is unchanged and still
              rendered here and in the directions list, and the advance
              action still calls the same handler, so multi-floor routes
              behave exactly as before. */}
          {!routeLoading && !routeError && isNavigating
            && (currentTransitionSegment || currentTransitionInstruction) && (
            <div className="s18-transition-bar">
              <span className="s18-transition-bar-icon" aria-hidden="true">
                <ConnectorIcon type={currentTransitionSegment?.transition_type} />
              </span>
              <span className="s18-transition-bar-text">
                {currentTransitionInstruction?.text
                  || t.continueTo(nextFloorSegment?.floor ?? '')}
              </span>
              <button
                type="button"
                className="s18-transition-bar-btn"
                onClick={handleAdvanceFloor}
              >
                {t.reachedFloor(nextFloorSegment?.floor ?? '')}
              </button>
            </div>
          )}

          {/* Confirm your location — the three ways a user can tell
              QuickRoute where they really are. All three converge on the
              existing resolver: "I have arrived" sets the same flag a
              destination QR sets, and the code field and the camera both
              call applyLocationCode(). No second validation path, and no
              duplicate "update my location" control elsewhere. */}
          {hasRealRoute && isNavigating && !hasArrived && (
            <div className="s18-confirm">
              <p className="s18-confirm-title">{t.confirmTitle}</p>
              <p className="s18-confirm-hint">{t.confirmHint}</p>

              <div className="s18-confirm-options">
                {/* A — type a code */}
                <div className="s18-confirm-card">
                  <span className="s18-confirm-card-head">
                    <PinIcon size={15} />
                    <span>{t.optionCode}</span>
                  </span>
                  <form className="s18-confirm-actions" onSubmit={handleScanSubmit}>
                    <input
                      className="s18-rescan-input"
                      type="text"
                      value={scanCode}
                      onChange={(e) => setScanCode(e.target.value)}
                      placeholder={t.rescanPlaceholder}
                      aria-label={t.rescanPlaceholder}
                      autoComplete="off"
                      disabled={scanBusy}
                    />
                    <button
                      type="submit"
                      className="s18-rescan-submit"
                      disabled={scanBusy || !scanCode.trim()}
                    >
                      {t.verify}
                    </button>
                  </form>
                </div>

                {/* B — camera */}
                <div className="s18-confirm-card">
                  <span className="s18-confirm-card-head">
                    <ScanIcon size={15} />
                    <span>{t.optionScan}</span>
                  </span>
                  <button
                    type="button"
                    className="s18-rescan-scan"
                    onClick={() => {
                      setScanError(null);
                      setScanNotice(null);
                      setScannerOpen(true);
                    }}
                    disabled={scanBusy}
                  >
                    <ScanIcon size={15} />
                    <span>{t.scanQr}</span>
                  </button>
                </div>
              </div>

              {scanError && <p className="s18-rescan-error">{scanError}</p>}
              {scanNotice && <p className="s18-rescan-notice">{scanNotice}</p>}
            </div>
          )}

          {/* Bottom action */}
          {floorSegments.length > 0 && instructionGroups.some((group) => group.length > 0) && (
            hasArrived ? (
              <button className="s18-done-btn" type="button" onClick={handleCancelNav}>
                <span>{t.endNav}</span>
              </button>
            ) : isNavigating ? (
              <button className="s18-cancel-btn" type="button" onClick={handleCancelNav}>
                {t.exitNav}
              </button>
            ) : (
              <button className="s18-nav-btn" type="button" onClick={handleStartNav}>
                <span>{t.startNav}</span>
                <NavArrow flip={isRTL} />
              </button>
            )
          )}

        </div>
        {/* Camera scanner. Renders only while open, so no camera track
            exists otherwise, and it resolves nothing itself. */}
        {scannerOpen && (
          <QrScanner
            onResult={handleScanResult}
            onClose={() => setScannerOpen(false)}
            labels={{
              title: t.scanTitle,
              hint: t.scanHint,
              cancel: t.rescanCancel,
              starting: t.scanStarting,
              denied: t.scanDenied,
              unavailable: t.scanUnavailable,
              unsupported: t.scanUnsupported,
              errorHint: t.scanErrorHint,
            }}
          />
        )}

      </div>
    </div>
  );
};

export default IndoorNavigationScreen;
