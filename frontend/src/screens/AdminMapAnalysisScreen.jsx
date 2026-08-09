import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { getMapById } from '../api/mapsApi';
import {
  startMapAnalysis,
  getLatestMapAnalysis,
  getAnalysisStatus,
  getAnalysisResult,
  saveReviewedResult,
  validateAnalysis,
  publishAnalysis,
  retryAnalysis,
  isMapAnalysisMockEnabled,
  getPublishedSemanticEntitiesForMap,
} from '../api/mapAnalysisApi';
import {
  statusBucket,
  canRetry,
  canReview,
  REVIEWABLE_ENTITY_ARRAYS,
  flattenReviewableEntities,
  countByReviewStatus,
  unresolvedBlockingReviewItems,
  isReadyToPublish,
  idsForAcceptAllHighConfidence,
  setEntityReviewStatus,
  correctEntity,
  resolveReviewItem,
  publishedEntityLabel,
} from '../utils/mapAnalysisHelpers';
import { formatFloorDisplay } from '../utils/mapGroupHelpers';
import { normalizeLocalizedText } from '../utils/localization';
import '../styles/adminScreens.css';

// Language-neutral field labels for the per-language Correct inputs —
// always shown in each language's own script regardless of the admin's
// current UI language, matching the existing language-switcher pill
// convention used elsewhere in the app (e.g. BuildingSelectionScreen.jsx).
const CORRECT_LANGUAGE_FIELDS = [
  { code: 'en', label: 'EN' },
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
];

// Admin Semantic Analysis Review screen — REPLACES the previous
// coordinate-based "detections/apply" review UI. This screen never shows
// or creates clickable coordinate markers: the semantic JSON this backend
// produces intentionally contains no coordinates at all (see
// backend/prompts/quickroute_semantic_map_import_v2.txt, section D:
// "Routing-Graph Separation"). RoutePoint placement stays exactly where
// it already was — the existing Add Point / Draw Walkable Path tools in
// Map Management — and is entirely unaffected by anything on this
// screen.
//
// Three-layer separation this screen enforces in the UI itself:
//   - the AI draft (aiResult) is rendered read-only and is never edited
//   - every accept/correct/reject/resolve action mutates a LOCAL copy of
//     reviewedResult only, which must be explicitly "Saved" to persist
//   - Publish is a separate, explicit, always-confirmed action that only
//     becomes available once nothing is left pending/blocking

const UI = {
  en: {
    title: 'Semantic Analysis Review',
    back: 'Back',
    mockBadge: 'Development mock data — never really published',
    noMapId: 'No map selected. Open this screen from Map Management.',
    loading: 'Loading…',
    noAnalysis: 'No analysis has been run for this map yet.',
    startAnalysis: 'Start Analysis',
    runAgain: 'Run Analysis Again',
    retry: 'Retry',
    statusQueued: 'Queued…',
    statusProcessing: (p) => `Analyzing… ${p}%`,
    statusCompleted: 'Analysis complete',
    analysisNoGraphMutationNotice:
      'Semantic analysis completed. No navigation points or connections were created.',
    statusFailed: 'Analysis failed',
    statusInvalid: 'The AI response failed validation',
    statusConfigRequired: 'Configuration required (missing ANTHROPIC_API_KEY)',
    statusCancelled: 'Cancelled',
    statusSuperseded: 'Superseded by a newer analysis',
    promptVersion: 'Prompt version',
    promptHash: 'Prompt hash',
    rawJson: 'Raw JSON',
    hideRawJson: 'Hide raw JSON',
    aiDraft: 'AI Draft (read-only)',
    reviewedDraft: 'Your Review',
    filterAll: 'All',
    filterUncertain: 'Uncertain only',
    filterBlocking: 'Blocking review items',
    acceptAllHigh: 'Accept All High Confidence',
    saveDraft: 'Save Review Draft',
    saved: 'Saved',
    unsavedChanges: 'Unsaved changes',
    validateBtn: 'Validate',
    publishBtn: 'Publish Semantic Data',
    publishing: 'Publishing…',
    publishedOk: 'Published successfully.',
    validationErrors: 'Validation errors',
    validationWarnings: 'Warnings',
    validationOk: 'Ready to publish.',
    accept: 'Accept',
    correct: 'Correct',
    reject: 'Reject',
    save: 'Save',
    cancel: 'Cancel',
    pending: 'Pending review',
    accepted: 'Accepted',
    corrected: 'Corrected',
    rejected: 'Rejected',
    original: 'Original',
    translations: 'EN / AR / HE',
    category: 'Category',
    floor: 'Floor',
    status: 'Status',
    confidence: 'Confidence',
    possibleNestedParentBadge: 'Inside:',
    possibleNestedParentHint:
      'This item may be nested inside another place. Review and confirm the exact relationship in "Create Destinations from Approved Analysis" after approving.',
    evidence: 'Evidence',
    reviewStatus: 'Review',
    actions: 'Actions',
    noEntities: 'No entities in this section.',
    summary: 'Summary',
    reviewItems: 'Review Items',
    blockingItem: 'Blocking',
    resolve: 'Resolve — Accepted',
    sourceDocuments: 'Source documents',
    unreadableAreas: 'Unreadable areas',
    publishedEntitiesTitle: 'Published Semantic Data',
    createDestination: 'Create Destination',
    emptyTranslation: 'No translation yet',
  },
  ar: {
    title: 'مراجعة التحليل الدلالي',
    back: 'رجوع',
    mockBadge: 'بيانات تجريبية للتطوير — لا يتم نشرها فعليًا أبدًا',
    noMapId: 'لم يتم تحديد خريطة. افتح هذه الشاشة من إدارة الخرائط.',
    loading: 'جارٍ التحميل…',
    noAnalysis: 'لم يتم تشغيل أي تحليل لهذه الخريطة بعد.',
    startAnalysis: 'بدء التحليل',
    runAgain: 'تشغيل التحليل مرة أخرى',
    retry: 'إعادة المحاولة',
    statusQueued: 'في الانتظار…',
    statusProcessing: (p) => `جارٍ التحليل… ${p}%`,
    statusCompleted: 'اكتمل التحليل',
    analysisNoGraphMutationNotice:
      'اكتمل التحليل الدلالي. لم يتم إنشاء نقاط أو روابط للمسارات.',
    statusFailed: 'فشل التحليل',
    statusInvalid: 'فشل التحقق من استجابة الذكاء الاصطناعي',
    statusConfigRequired: 'مطلوب إعداد (مفتاح ANTHROPIC_API_KEY مفقود)',
    statusCancelled: 'تم الإلغاء',
    statusSuperseded: 'تم استبداله بتحليل أحدث',
    promptVersion: 'إصدار الطلب',
    promptHash: 'بصمة الطلب',
    rawJson: 'JSON الخام',
    hideRawJson: 'إخفاء JSON الخام',
    aiDraft: 'مسودة الذكاء الاصطناعي (للقراءة فقط)',
    reviewedDraft: 'مراجعتك',
    filterAll: 'الكل',
    filterUncertain: 'غير المؤكد فقط',
    filterBlocking: 'عناصر المراجعة الحاجبة',
    acceptAllHigh: 'قبول جميع العناصر عالية الثقة',
    saveDraft: 'حفظ مسودة المراجعة',
    saved: 'تم الحفظ',
    unsavedChanges: 'تغييرات غير محفوظة',
    validateBtn: 'تحقق',
    publishBtn: 'نشر البيانات الدلالية',
    publishing: 'جارٍ النشر…',
    publishedOk: 'تم النشر بنجاح.',
    validationErrors: 'أخطاء التحقق',
    validationWarnings: 'تحذيرات',
    validationOk: 'جاهز للنشر.',
    accept: 'قبول',
    correct: 'تصحيح',
    reject: 'رفض',
    save: 'حفظ',
    cancel: 'إلغاء',
    pending: 'قيد المراجعة',
    accepted: 'مقبول',
    corrected: 'تم التصحيح',
    rejected: 'مرفوض',
    original: 'النص الأصلي',
    translations: 'EN / AR / HE',
    category: 'الفئة',
    floor: 'الطابق',
    status: 'الحالة',
    confidence: 'الثقة',
    possibleNestedParentBadge: 'داخل:',
    possibleNestedParentHint:
      'قد يكون هذا العنصر داخل مكان آخر. راجعي العلاقة الدقيقة وأكديها في "إنشاء الوجهات من التحليل المعتمد" بعد الموافقة.',
    evidence: 'الأدلة',
    reviewStatus: 'المراجعة',
    actions: 'إجراءات',
    noEntities: 'لا توجد عناصر في هذا القسم.',
    summary: 'الملخص',
    reviewItems: 'عناصر المراجعة',
    blockingItem: 'حاجب',
    resolve: 'حل — مقبول',
    sourceDocuments: 'المستندات المصدر',
    unreadableAreas: 'مناطق غير مقروءة',
    publishedEntitiesTitle: 'البيانات الدلالية المنشورة',
    createDestination: 'إنشاء وجهة',
    emptyTranslation: 'لا توجد ترجمة بعد',
  },
  he: {
    title: 'סקירת ניתוח סמנטי',
    back: 'חזרה',
    mockBadge: 'נתוני פיתוח לדוגמה — לעולם לא מתפרסמים באמת',
    noMapId: 'לא נבחרה מפה. פתח מסך זה מניהול מפות.',
    loading: 'טוען…',
    noAnalysis: 'טרם הופעל ניתוח למפה זו.',
    startAnalysis: 'התחל ניתוח',
    runAgain: 'הפעל ניתוח שוב',
    retry: 'נסה שוב',
    statusQueued: 'בהמתנה…',
    statusProcessing: (p) => `מנתח… ${p}%`,
    statusCompleted: 'הניתוח הושלם',
    analysisNoGraphMutationNotice:
      'הניתוח הסמנטי הושלם. לא נוצרו נקודות או חיבורים לניווט.',
    statusFailed: 'הניתוח נכשל',
    statusInvalid: 'אימות תגובת ה-AI נכשל',
    statusConfigRequired: 'נדרשת תצורה (חסר ANTHROPIC_API_KEY)',
    statusCancelled: 'בוטל',
    statusSuperseded: 'הוחלף בניתוח חדש יותר',
    promptVersion: 'גרסת הנחיה',
    promptHash: 'טביעת אצבע של ההנחיה',
    rawJson: 'JSON גולמי',
    hideRawJson: 'הסתר JSON גולמי',
    aiDraft: 'טיוטת AI (לקריאה בלבד)',
    reviewedDraft: 'הסקירה שלך',
    filterAll: 'הכל',
    filterUncertain: 'לא ודאי בלבד',
    filterBlocking: 'פריטי סקירה חוסמים',
    acceptAllHigh: 'אשר את כל הביטחון הגבוה',
    saveDraft: 'שמור טיוטת סקירה',
    saved: 'נשמר',
    unsavedChanges: 'שינויים לא שמורים',
    validateBtn: 'אמת',
    publishBtn: 'פרסם נתונים סמנטיים',
    publishing: 'מפרסם…',
    publishedOk: 'פורסם בהצלחה.',
    validationErrors: 'שגיאות אימות',
    validationWarnings: 'אזהרות',
    validationOk: 'מוכן לפרסום.',
    accept: 'אשר',
    correct: 'תקן',
    reject: 'דחה',
    save: 'שמור',
    cancel: 'ביטול',
    pending: 'ממתין לסקירה',
    accepted: 'אושר',
    corrected: 'תוקן',
    rejected: 'נדחה',
    original: 'מקורי',
    translations: 'EN / AR / HE',
    category: 'קטגוריה',
    possibleNestedParentBadge: 'בתוך:',
    possibleNestedParentHint:
      'ייתכן שפריט זה מקונן בתוך מקום אחר. יש לבדוק ולאשר את הקשר המדויק ב"יצירת יעדים מהניתוח שאושר" לאחר האישור.',
    floor: 'קומה',
    status: 'סטטוס',
    confidence: 'ביטחון',
    evidence: 'ראיות',
    reviewStatus: 'סקירה',
    actions: 'פעולות',
    noEntities: 'אין ישויות בקטע זה.',
    summary: 'סיכום',
    reviewItems: 'פריטי סקירה',
    blockingItem: 'חוסם',
    resolve: 'פתור — אושר',
    sourceDocuments: 'מסמכי מקור',
    unreadableAreas: 'אזורים לא קריאים',
    publishedEntitiesTitle: 'נתונים סמנטיים שפורסמו',
    createDestination: 'צור יעד',
    emptyTranslation: 'אין תרגום עדיין',
  },
};

const STATUS_TEXT_KEY = {
  queued: 'statusQueued',
  processing: 'statusProcessing',
  completed: 'statusCompleted',
  failed: 'statusFailed',
  invalid_output: 'statusInvalid',
  configuration_required: 'statusConfigRequired',
  cancelled: 'statusCancelled',
  superseded: 'statusSuperseded',
};

const REVIEW_BADGE_COLOR = {
  pending: '#b47b09',
  accepted: '#1f9d55',
  corrected: '#2d6cdf',
  rejected: '#a92323',
};

const AdminMapAnalysisScreen = () => {
  const { lang } = useLang();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const mapId = searchParams.get('mapId');
  const initialAnalysisId = searchParams.get('analysisId');

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;
  const isMock = isMapAnalysisMockEnabled();

  const [map, setMap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [analysis, setAnalysis] = useState(null); // normalized detail
  const [result, setResult] = useState(null); // { aiResult, reviewedResult, reviewRevision }
  const [reviewed, setReviewed] = useState(null); // local working copy
  const [reviewRevision, setReviewRevision] = useState(0);
  const [dirty, setDirty] = useState(false);

  const [filter, setFilter] = useState('all');
  const [showRawJson, setShowRawJson] = useState(false);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState(null);
  const [publishSuccess, setPublishSuccess] = useState(null);
  const [editingId, setEditingId] = useState(null);
  // Independently-editable AR/HE/EN drafts (Section 4 of the multilingual
  // spec) — replaces the old single editDraftName/names.original-only
  // flow. Never seeded from/copied into another language automatically;
  // normalizeLocalizedText() only ever fills in "" for a language that
  // has no stored value yet, never guesses one language from another.
  const [editDraftNames, setEditDraftNames] = useState({ ar: '', he: '', en: '' });
  const [publishedEntities, setPublishedEntities] = useState([]);

  useEffect(() => {
    if (!mapId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    getMapById(mapId)
      .then((m) => { if (!cancelled) setMap(m); })
      .catch(() => { if (!cancelled) setMap(null); });
    return () => { cancelled = true; };
  }, [mapId]);

  const loadAnalysis = useCallback(async () => {
    if (!mapId) return;
    setError('');
    try {
      let current;
      if (initialAnalysisId) {
        current = await getAnalysisStatus(initialAnalysisId);
      } else {
        const latest = await getLatestMapAnalysis(mapId);
        current = latest ? await getAnalysisStatus(latest.analysisId) : null;
      }
      setAnalysis(current);
    } catch (err) {
      setError(err.isServiceUnavailable ? err.message : (err.message || 'Failed to load analysis'));
    } finally {
      setLoading(false);
    }
  }, [mapId, initialAnalysisId]);

  useEffect(() => { loadAnalysis(); }, [loadAnalysis]);

  // Light polling while genuinely in flight.
  useEffect(() => {
    if (!analysis || !['queued', 'processing'].includes(analysis.status)) return undefined;
    const timer = setTimeout(loadAnalysis, 2000);
    return () => clearTimeout(timer);
  }, [analysis, loadAnalysis]);

  // Load the full result once the analysis is completed.
  useEffect(() => {
    if (!analysis || analysis.status !== 'completed') return;
    let cancelled = false;
    getAnalysisResult(analysis.analysisId)
      .then((r) => {
        if (cancelled) return;
        setResult(r);
        setReviewed(r.reviewedResult || r.aiResult);
        setReviewRevision(r.reviewRevision || 0);
        setDirty(false);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load analysis result');
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis?.analysisId, analysis?.status]);

  // Section 17 — "Create Destination": loads the Map's currently active
  // published semantic entities whenever this analysis has been
  // published (either already, from a previous session, or just now via
  // handlePublish below). Never loads anything before publish — an
  // admin can never "Create Destination" from an unpublished AI draft.
  useEffect(() => {
    if (!mapId) return;
    if (!analysis?.publishedAnalysisId && !publishSuccess) {
      setPublishedEntities([]);
      return;
    }
    let cancelled = false;
    getPublishedSemanticEntitiesForMap(mapId)
      .then((list) => { if (!cancelled) setPublishedEntities(list); })
      .catch(() => { if (!cancelled) setPublishedEntities([]); });
    return () => { cancelled = true; };
  }, [mapId, analysis?.publishedAnalysisId, publishSuccess]);

  // Section 6 of the multilingual spec: creating a Destination from an
  // approved semantic entity must copy ALL of its approved translations
  // (not just whichever one this admin currently has the UI set to) plus
  // the semantic-entity linkage, so AdminRoomsScreen's form can prefill
  // every language independently and the created Room preserves a real
  // traceability relation back to the entity it came from.
  const handleCreateDestination = (entity) => {
    const names = entity.names || {};
    // The EN field specifically is the room's required legacy name_en —
    // prefer a real English translation, then the AI's raw detected
    // text, then whatever the current UI language happens to resolve to,
    // so it's never left blank even when no English translation exists.
    const nameEn = names.en || names.original || publishedEntityLabel(entity, lang);
    const params = new URLSearchParams({
      prefillName: nameEn || '',
      prefillNameAr: names.ar || '',
      prefillNameHe: names.he || '',
      prefillMapId: mapId || '',
      prefillSemanticPublicationId: entity.publicationId || '',
      prefillSemanticEntityExternalId: entity.entityExternalId || '',
      prefillSemanticEntityType: entity.entityType || '',
    });
    navigate(`/admin/rooms?${params.toString()}`);
  };

  const handleStart = async (force) => {
    if (!mapId) return;
    setBusy(true);
    setError('');
    try {
      const started = await startMapAnalysis(mapId, { force });
      setAnalysis(await getAnalysisStatus(started.analysisId));
      setResult(null);
      setReviewed(null);
      setPublishSuccess(null);
      setValidation(null);
    } catch (err) {
      setError(err.message || 'Failed to start analysis');
    } finally {
      setBusy(false);
    }
  };

  const handleRetry = async () => {
    if (!analysis?.analysisId) return;
    setBusy(true);
    try {
      setAnalysis(await getAnalysisStatus(analysis.analysisId).then(async () => {
        await retryAnalysis(analysis.analysisId);
        return getAnalysisStatus(analysis.analysisId);
      }));
    } catch (err) {
      setError(err.message || 'Failed to retry analysis');
    } finally {
      setBusy(false);
    }
  };

  const applyMutation = (mutatorResult) => {
    setReviewed(mutatorResult);
    setDirty(true);
    setPublishSuccess(null);
  };

  const handleAccept = (entityType, externalId) => {
    applyMutation(setEntityReviewStatus(reviewed, entityType, externalId, 'accepted'));
  };

  const handleReject = (entityType, externalId) => {
    applyMutation(setEntityReviewStatus(reviewed, entityType, externalId, 'rejected'));
  };

  // `currentNames` is the entity's full names object (original + en/ar/he)
  // — "original" (the AI's raw detected text) is deliberately excluded
  // from the editable draft below and stays untouched/read-only for the
  // lifetime of the edit, exactly as the review UI displays it elsewhere.
  const startCorrect = (entityType, externalId, currentNames) => {
    setEditingId(`${entityType}::${externalId}`);
    const normalized = normalizeLocalizedText(currentNames);
    setEditDraftNames({ ar: normalized.ar, he: normalized.he, en: normalized.en });
  };

  const setEditDraftLanguage = (langCode, value) => {
    // Each language field is updated independently — never touches the
    // other two, so correcting the Arabic name can never silently blank
    // out or overwrite the already-approved Hebrew/English ones.
    setEditDraftNames((prev) => ({ ...prev, [langCode]: value }));
  };

  const saveCorrect = (entityType, externalId) => {
    const existingNames = getEntity(entityType, externalId)?.names || {};
    applyMutation(
      correctEntity(reviewed, entityType, externalId, {
        names: {
          ...existingNames,
          en: editDraftNames.en.trim() || null,
          ar: editDraftNames.ar.trim() || null,
          he: editDraftNames.he.trim() || null,
        },
      }),
    );
    setEditingId(null);
  };

  const getEntity = (entityType, externalId) => {
    const config = REVIEWABLE_ENTITY_ARRAYS.find((entry) => entry.key === entityType);
    if (!config || !reviewed) return null;
    return (reviewed[entityType] || []).find((item) => item[config.idField] === externalId);
  };

  const handleAcceptAllHigh = () => {
    let next = reviewed;
    idsForAcceptAllHighConfidence(reviewed).forEach(({ entityType, externalId }) => {
      next = setEntityReviewStatus(next, entityType, externalId, 'accepted');
    });
    applyMutation(next);
  };

  const handleResolveReviewItem = (reviewItemExternalId) => {
    applyMutation(
      resolveReviewItem(reviewed, reviewItemExternalId, { status: 'accepted' }),
    );
  };

  const handleSaveDraft = async () => {
    if (!analysis?.analysisId || !reviewed) return;
    setBusy(true);
    setError('');
    try {
      const saved = await saveReviewedResult(analysis.analysisId, {
        expectedRevision: reviewRevision,
        reviewedResult: reviewed,
      });
      setReviewRevision(saved.reviewRevision);
      setDirty(false);
    } catch (err) {
      setError(err.message || 'Failed to save review draft');
    } finally {
      setBusy(false);
    }
  };

  const handleValidate = async () => {
    if (!analysis?.analysisId) return;
    setBusy(true);
    try {
      const result2 = await validateAnalysis(analysis.analysisId);
      setValidation(result2);
    } catch (err) {
      setError(err.message || 'Failed to validate');
    } finally {
      setBusy(false);
    }
  };

  const handlePublish = async () => {
    if (!analysis?.analysisId) return;
    if (dirty) {
      setError('Save your review draft before publishing.');
      return;
    }
    // eslint-disable-next-line no-alert
    if (!window.confirm(t.publishBtn + '?')) return;
    setBusy(true);
    setError('');
    try {
      const published = await publishAnalysis(analysis.analysisId);
      setPublishSuccess(published);
    } catch (err) {
      setError(err.message || 'Failed to publish');
    } finally {
      setBusy(false);
    }
  };

  const reviewCounts = useMemo(() => countByReviewStatus(reviewed), [reviewed]);
  const blockingItems = useMemo(() => unresolvedBlockingReviewItems(reviewed), [reviewed]);
  const readyLocally = useMemo(() => isReadyToPublish(reviewed), [reviewed]);

  const filteredFlat = useMemo(() => {
    const flat = flattenReviewableEntities(reviewed);
    if (filter === 'uncertain') {
      return flat.filter(({ item }) => Number(item.confidence) < 0.7);
    }
    return flat;
  }, [reviewed, filter]);

  const groupedByType = useMemo(() => {
    const groups = {};
    filteredFlat.forEach(({ entityType, item }) => {
      groups[entityType] = groups[entityType] || [];
      groups[entityType].push(item);
    });
    return groups;
  }, [filteredFlat]);

  if (!mapId) {
    return (
      <div className="layout-wrapper">
        <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
          <div className="adm-content">
            <div className="adm-empty"><div className="adm-empty-txt">{t.noMapId}</div></div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button className={`adm-back-btn${isRTL ? ' adm-back-btn-rtl' : ''}`} onClick={() => navigate(-1)}>
              {t.back}
            </button>
          </div>
          <div className="adm-inner-heading">
            <h1 className="adm-inner-title">
              {t.title}
              {map && ` — [${map.mapGroupCode || ''}] ${formatFloorDisplay(map.floor, map.floorLabel)} — ${map.title}`}
            </h1>
          </div>
        </div>

        <div className="adm-content">
          {isMock && (
            <div className="adm-tag" style={{ background: '#fff3cd', color: '#8a6116', marginBottom: 12 }}>
              {t.mockBadge}
            </div>
          )}

          {error && (
            <div style={{ marginBottom: 16, padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
              {error}
            </div>
          )}

          {loading && <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>}

          {!loading && !analysis && (
            <div className="adm-empty">
              <div className="adm-empty-txt">{t.noAnalysis}</div>
              <button className="adm-btn adm-btn-primary" onClick={() => handleStart(false)} disabled={busy}>
                {t.startAnalysis}
              </button>
            </div>
          )}

          {!loading && analysis && (
            <>
              <div className="adm-form-card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>
                    {STATUS_TEXT_KEY[analysis.status] === 'statusProcessing'
                      ? t.statusProcessing(analysis.progress || 0)
                      : t[STATUS_TEXT_KEY[analysis.status]] || analysis.status}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {canRetry(analysis.status) && (
                      <button className="adm-btn adm-btn-secondary" onClick={handleRetry} disabled={busy}>
                        {t.retry}
                      </button>
                    )}
                    {analysis.status === 'completed' && (
                      <button className="adm-btn adm-btn-secondary" onClick={() => handleStart(true)} disabled={busy}>
                        {t.runAgain}
                      </button>
                    )}
                  </div>
                </div>
                {analysis.errorMessage && (
                  <div style={{ marginTop: 8, fontSize: 12.5, color: '#a92323' }}>{analysis.errorMessage}</div>
                )}
                {analysis.status === 'completed' && (
                  <div
                    style={{
                      marginTop: 8,
                      fontSize: 12.5,
                      color: '#1f6d3f',
                      background: '#eafaf1',
                      border: '1px solid #bfe8cf',
                      borderRadius: 8,
                      padding: '6px 10px',
                    }}
                  >
                    {t.analysisNoGraphMutationNotice}
                  </div>
                )}
                <div style={{ marginTop: 8, fontSize: 11.5, color: '#6c7a8c' }}>
                  {t.promptVersion}: {analysis.promptVersion} · {t.promptHash}: {analysis.promptSha256?.slice(0, 12)}…
                </div>
              </div>

              {canReview(analysis.status) && reviewed && (
                <>
                  <div className="adm-btn-row" style={{ flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
                    <select
                      className="adm-form-select"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                      style={{ maxWidth: 220 }}
                    >
                      <option value="all">{t.filterAll}</option>
                      <option value="uncertain">{t.filterUncertain}</option>
                    </select>
                    <button className="adm-btn adm-btn-secondary" onClick={handleAcceptAllHigh}>
                      {t.acceptAllHigh}
                    </button>
                    <button
                      className="adm-btn adm-btn-secondary"
                      onClick={handleSaveDraft}
                      disabled={busy || !dirty}
                    >
                      {dirty ? t.saveDraft : t.saved}
                    </button>
                    <button className="adm-btn adm-btn-secondary" onClick={handleValidate} disabled={busy}>
                      {t.validateBtn}
                    </button>
                    <button
                      className="adm-btn adm-btn-primary"
                      onClick={handlePublish}
                      disabled={busy || dirty || !readyLocally}
                    >
                      {busy ? t.publishing : t.publishBtn}
                    </button>
                    <button className="adm-btn adm-btn-secondary" onClick={() => setShowRawJson((v) => !v)}>
                      {showRawJson ? t.hideRawJson : t.rawJson}
                    </button>
                  </div>

                  <div style={{ fontSize: 12, color: '#6c7a8c', marginBottom: 10 }}>
                    {t.pending}: {reviewCounts.pending} · {t.accepted}: {reviewCounts.accepted} ·{' '}
                    {t.corrected}: {reviewCounts.corrected} · {t.rejected}: {reviewCounts.rejected}
                    {dirty && <span style={{ color: '#b47b09', marginInlineStart: 8 }}>({t.unsavedChanges})</span>}
                  </div>

                  {publishSuccess && (
                    <div style={{ marginBottom: 12, padding: 10, borderRadius: 10, background: '#e7f8ee', color: '#1f9d55', fontSize: 13 }}>
                      {t.publishedOk} ({publishSuccess.publicationId})
                    </div>
                  )}

                  {publishedEntities.length > 0 && (
                    <div className="adm-form-card" style={{ marginBottom: 16 }}>
                      <div className="adm-form-card-title">{t.publishedEntitiesTitle}</div>
                      {publishedEntities.map((entity) => (
                        <div
                          key={`${entity.publicationId}-${entity.entityExternalId}`}
                          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderTop: '1px solid #eee' }}
                        >
                          <span style={{ fontSize: 12.5 }}>
                            {publishedEntityLabel(entity, lang)}
                            {entity.category && (
                              <span style={{ color: '#8a99ad', marginInlineStart: 6 }}>({entity.category})</span>
                            )}
                          </span>
                          <button
                            type="button"
                            className="adm-btn adm-btn-secondary"
                            style={{ fontSize: 11, padding: '3px 8px' }}
                            onClick={() => handleCreateDestination(entity)}
                          >
                            {t.createDestination}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {validation && (
                    <div className="adm-form-card" style={{ marginBottom: 16 }}>
                      {validation.valid ? (
                        <div style={{ color: '#1f9d55', fontSize: 13 }}>{t.validationOk}</div>
                      ) : (
                        <>
                          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{t.validationErrors}</div>
                          <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12.5, color: '#a92323' }}>
                            {validation.errors.map((msg, i) => <li key={i}>{msg}</li>)}
                          </ul>
                        </>
                      )}
                      {validation.warnings?.length > 0 && (
                        <>
                          <div style={{ fontWeight: 700, fontSize: 13, marginTop: 8 }}>{t.validationWarnings}</div>
                          <ul style={{ margin: 0, paddingInlineStart: 18, fontSize: 12.5, color: '#b47b09' }}>
                            {validation.warnings.map((msg, i) => <li key={i}>{msg}</li>)}
                          </ul>
                        </>
                      )}
                    </div>
                  )}

                  {blockingItems.length > 0 && (
                    <div className="adm-form-card" style={{ marginBottom: 16 }}>
                      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{t.reviewItems}</div>
                      {blockingItems.map((item) => (
                        <div
                          key={item.review_item_external_id}
                          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderTop: '1px solid #eee' }}
                        >
                          <span style={{ fontSize: 12.5 }}>
                            <strong style={{ color: '#a92323' }}>[{t.blockingItem}]</strong> {item.reason || item.visible_text || item.review_item_external_id}
                          </span>
                          <button
                            className="adm-btn adm-btn-secondary"
                            style={{ fontSize: 11, padding: '3px 8px' }}
                            onClick={() => handleResolveReviewItem(item.review_item_external_id)}
                          >
                            {t.resolve}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {REVIEWABLE_ENTITY_ARRAYS.map(({ key, idField, label }) => {
                    const items = groupedByType[key] || [];
                    if (items.length === 0 && filter !== 'all') return null;
                    return (
                      <div key={key} className="adm-form-card" style={{ marginBottom: 16 }}>
                        <div className="adm-form-card-title">{label} ({items.length})</div>
                        {items.length === 0 && (
                          <div style={{ fontSize: 12.5, color: '#6c7a8c' }}>{t.noEntities}</div>
                        )}
                        {items.length > 0 && (
                          <table className="adm-table" style={{ width: '100%', fontSize: 12.5 }}>
                            <thead>
                              <tr>
                                <th>{t.original}</th>
                                <th>{t.translations}</th>
                                <th>{t.category}</th>
                                <th>{t.floor}</th>
                                <th>{t.status}</th>
                                <th>{t.confidence}</th>
                                <th>{t.reviewStatus}</th>
                                <th>{t.actions}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {items.map((item) => {
                                const externalId = item[idField];
                                const rowKey = `${key}::${externalId}`;
                                const reviewStatus = item.review?.status || 'pending';
                                const isEditing = editingId === rowKey;
                                return (
                                  <tr key={rowKey}>
                                    <td>
                                      {/* "original" (the AI's raw detected text) is always
                                          read-only — Correct never edits it, only the
                                          independent AR/HE/EN translation fields below. */}
                                      {item.names?.original || '—'}
                                    </td>
                                    <td style={{ fontSize: 11, color: '#6c7a8c' }}>
                                      {isEditing ? (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
                                          {CORRECT_LANGUAGE_FIELDS.map(({ code, label }) => (
                                            <div key={code} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                              <span style={{ width: 32, flexShrink: 0, fontWeight: 700, color: '#8a99ad' }}>
                                                {label}
                                              </span>
                                              <input
                                                className="adm-form-input"
                                                style={{ fontSize: 12, padding: '3px 6px', flex: 1 }}
                                                value={editDraftNames[code]}
                                                placeholder={t.emptyTranslation}
                                                onChange={(e) => setEditDraftLanguage(code, e.target.value)}
                                              />
                                            </div>
                                          ))}
                                        </div>
                                      ) : (
                                        [item.names?.en, item.names?.ar, item.names?.he].filter(Boolean).join(' / ') || (
                                          <span>{t.emptyTranslation}</span>
                                        )
                                      )}
                                    </td>
                                    <td>
                                      {item.category || item[`${key.replace(/s$/, '')}_type`] || '—'}
                                      {(item.inside_place_external_id || item.belongs_to_place_external_id) && (
                                        <div
                                          title={t.possibleNestedParentHint}
                                          style={{
                                            fontSize: 10.5,
                                            color: '#8e44ad',
                                            marginTop: 2,
                                            fontWeight: 700,
                                          }}
                                        >
                                          {t.possibleNestedParentBadge}{' '}
                                          {item.inside_place_external_id || item.belongs_to_place_external_id}
                                        </div>
                                      )}
                                    </td>
                                    <td>
                                      {/* Section 4: the code shown here is always the backend's
                                          authoritative floor_XXX (GET /result now returns a
                                          normalized view derived from this map's real Map.floor —
                                          never the AI's independently-invented first-entity id).
                                          The friendly "Floor 2" text below is purely a label; the
                                          code itself is what item.floor_external_id already is. */}
                                      {item.floor_external_id || '—'}
                                      {map && (
                                        <div style={{ fontSize: 10.5, color: '#8a8a8a', marginTop: 2 }}>
                                          {formatFloorDisplay(map.floor, map.floorLabel)}
                                        </div>
                                      )}
                                    </td>
                                    <td>{item.status || '—'}</td>
                                    <td>{item.confidence != null ? `${Math.round(item.confidence * 100)}%` : '—'}</td>
                                    <td>
                                      <span style={{ color: REVIEW_BADGE_COLOR[reviewStatus], fontWeight: 700 }}>
                                        {t[reviewStatus] || reviewStatus}
                                      </span>
                                    </td>
                                    <td>
                                      {isEditing ? (
                                        <>
                                          <button className="adm-icon-btn" onClick={() => saveCorrect(key, externalId)}>
                                            {t.save}
                                          </button>
                                          <button className="adm-icon-btn" onClick={() => setEditingId(null)}>
                                            {t.cancel}
                                          </button>
                                        </>
                                      ) : (
                                        <>
                                          <button
                                            className="adm-icon-btn"
                                            style={{ color: '#1f9d55' }}
                                            onClick={() => handleAccept(key, externalId)}
                                          >
                                            {t.accept}
                                          </button>
                                          <button
                                            className="adm-icon-btn"
                                            onClick={() => startCorrect(key, externalId, item.names)}
                                          >
                                            {t.correct}
                                          </button>
                                          <button
                                            className="adm-icon-btn adm-icon-btn-danger"
                                            onClick={() => handleReject(key, externalId)}
                                          >
                                            {t.reject}
                                          </button>
                                        </>
                                      )}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        )}
                      </div>
                    );
                  })}

                  {showRawJson && (
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                      <div style={{ flex: '1 1 400px', minWidth: 300 }}>
                        <div className="adm-form-card-title">{t.aiDraft}</div>
                        <pre style={{ fontSize: 10.5, background: '#0f172a', color: '#d7e3f5', padding: 10, borderRadius: 8, maxHeight: 400, overflow: 'auto' }}>
                          {JSON.stringify(result?.aiResult, null, 2)}
                        </pre>
                      </div>
                      <div style={{ flex: '1 1 400px', minWidth: 300 }}>
                        <div className="adm-form-card-title">{t.reviewedDraft}</div>
                        <pre style={{ fontSize: 10.5, background: '#0f172a', color: '#d7e3f5', padding: 10, borderRadius: 8, maxHeight: 400, overflow: 'auto' }}>
                          {JSON.stringify(reviewed, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AdminMapAnalysisScreen;
