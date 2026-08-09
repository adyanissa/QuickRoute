import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import {
  getMapsNavigationOverview,
  previewMultiMapGeneratedCleanup,
  applyMultiMapGeneratedCleanup,
  previewMultiMapFullReset,
  applyMultiMapFullReset,
} from '../api/mapsApi';
import { resolveApiErrorMessage } from '../utils/apiErrors';
import '../styles/adminScreens.css';

// Navigation-data-problem task, Part 4 — Super Admin-only screen for
// cleaning up navigation data across MULTIPLE existing Maps at once
// (the per-map actions on AdminMapScreen only ever handle one Map at a
// time). Every write here is strictly select -> preview -> explicit
// confirm -> apply; nothing on this screen ever runs automatically, and
// nothing here is reachable at all without the backend's own
// require_super_admin gate on every /api/navigation-cleanup/* endpoint
// (RequireSuperAdmin on the route is a UI convenience, not the real
// security boundary).

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const MULTI_RESET_PHRASE = 'RESET SELECTED NAVIGATION DATA';

const UI = {
  en: {
    title: 'Navigation Data Cleanup (All Maps)',
    back: 'Back',
    loading: 'Loading maps…',
    loadError: 'Failed to load the maps overview',
    empty: 'No maps found.',
    colBuilding: 'Building',
    colMapGroup: 'Map Group',
    colFloor: 'Floor',
    colTotalPoints: 'Total Points',
    colGenerated: 'Generated',
    colManual: 'Manual',
    colUnknown: 'Unknown/Legacy',
    colEdges: 'Edges',
    selectAll: 'Select all',
    selectedCount: (n) => `${n} map(s) selected`,
    previewGeneratedBtn: 'Preview Generated-Only Cleanup',
    applyGeneratedBtn: 'Delete Generated Data on Selected Maps',
    previewResetBtn: 'Preview Full Reset',
    applyResetBtn: 'Reset All Navigation Data on Selected Maps',
    noSelection: 'Select at least one map first.',
    previewTitleGenerated: 'Generated-Only Cleanup — Preview',
    previewTitleReset: 'Full Navigation Reset — Preview',
    perMapGenerated: (name, points, edges) =>
      `${name}: ${points} generated point(s), ${edges} generated connection(s)`,
    perMapReset: (name, points, edges) =>
      `${name}: ${points} point(s), ${edges} connection(s) — ALL of this map's navigation data`,
    totalsGenerated: (points, edges) =>
      `Total across selected maps: ${points} generated point(s), ${edges} generated connection(s).`,
    totalsReset: (points, edges) =>
      `Total across selected maps: ${points} point(s), ${edges} connection(s) will be permanently deleted.`,
    resetWarning:
      'This deletes ALL route points and connections — including manually added ones — on every selected map. This cannot be undone.',
    confirmPhraseInstructions: `Type the exact phrase "${MULTI_RESET_PHRASE}" to confirm.`,
    confirmPhrasePlaceholder: MULTI_RESET_PHRASE,
    cancel: 'Cancel',
    confirmGenerated: 'Delete Generated Data',
    confirmReset: 'Permanently Delete All Navigation Data',
    applying: 'Applying…',
    applyFailed: 'The cleanup action failed',
    applySummaryGenerated: (points, edges, mapCount) =>
      `Removed ${points} generated route point(s) and ${edges} generated connection(s) across ${mapCount} map(s).`,
    applySummaryReset: (points, edges, mapCount) =>
      `Deleted ${points} route point(s) and ${edges} connection(s) across ${mapCount} map(s).`,
  },
  ar: {
    title: 'تنظيف بيانات المسارات (جميع الخرائط)',
    back: 'رجوع',
    loading: 'جارٍ تحميل الخرائط…',
    loadError: 'فشل تحميل نظرة عامة على الخرائط',
    empty: 'لا توجد خرائط.',
    colBuilding: 'المبنى',
    colMapGroup: 'مجموعة الخرائط',
    colFloor: 'الطابق',
    colTotalPoints: 'إجمالي النقاط',
    colGenerated: 'مولّدة',
    colManual: 'يدوية',
    colUnknown: 'غير مؤكدة/قديمة',
    colEdges: 'الاتصالات',
    selectAll: 'تحديد الكل',
    selectedCount: (n) => `تم تحديد ${n} خريطة`,
    previewGeneratedBtn: 'معاينة حذف البيانات المولّدة',
    applyGeneratedBtn: 'حذف البيانات المولّدة من الخرائط المحددة',
    previewResetBtn: 'معاينة إعادة الضبط الكامل',
    applyResetBtn: 'إعادة ضبط جميع بيانات المسارات في الخرائط المحددة',
    noSelection: 'الرجاء تحديد خريطة واحدة على الأقل.',
    previewTitleGenerated: 'حذف البيانات المولّدة — معاينة',
    previewTitleReset: 'إعادة ضبط بيانات المسارات بالكامل — معاينة',
    perMapGenerated: (name, points, edges) =>
      `${name}: ${points} نقطة مولّدة، ${edges} اتصال مولّد`,
    perMapReset: (name, points, edges) =>
      `${name}: ${points} نقطة، ${edges} اتصال — كل بيانات المسارات في هذه الخريطة`,
    totalsGenerated: (points, edges) =>
      `الإجمالي عبر الخرائط المحددة: ${points} نقطة مولّدة، ${edges} اتصال مولّد.`,
    totalsReset: (points, edges) =>
      `الإجمالي عبر الخرائط المحددة: سيتم حذف ${points} نقطة و ${edges} اتصال نهائيًا.`,
    resetWarning:
      'سيؤدي هذا إلى حذف جميع نقاط واتصالات المسارات — بما في ذلك ما أُضيف يدويًا — في كل خريطة محددة. لا يمكن التراجع عن هذا الإجراء.',
    confirmPhraseInstructions: `اكتب العبارة بالضبط "${MULTI_RESET_PHRASE}" للتأكيد.`,
    confirmPhrasePlaceholder: MULTI_RESET_PHRASE,
    cancel: 'إلغاء',
    confirmGenerated: 'حذف البيانات المولّدة',
    confirmReset: 'حذف جميع بيانات المسارات نهائيًا',
    applying: 'جارٍ التنفيذ…',
    applyFailed: 'فشل إجراء التنظيف',
    applySummaryGenerated: (points, edges, mapCount) =>
      `تم حذف ${points} نقطة مسار مولّدة و ${edges} اتصال مولّد عبر ${mapCount} خريطة.`,
    applySummaryReset: (points, edges, mapCount) =>
      `تم حذف ${points} نقطة مسار و ${edges} اتصال عبر ${mapCount} خريطة.`,
  },
  he: {
    title: 'ניקוי נתוני ניווט (כל המפות)',
    back: 'חזרה',
    loading: 'טוען מפות…',
    loadError: 'טעינת סקירת המפות נכשלה',
    empty: 'לא נמצאו מפות.',
    colBuilding: 'מבנה',
    colMapGroup: 'קבוצת מפות',
    colFloor: 'קומה',
    colTotalPoints: 'סה"כ נקודות',
    colGenerated: 'שנוצרו אוטומטית',
    colManual: 'ידניות',
    colUnknown: 'לא ודאיות/ישנות',
    colEdges: 'חיבורים',
    selectAll: 'בחר הכול',
    selectedCount: (n) => `${n} מפות נבחרו`,
    previewGeneratedBtn: 'תצוגה מקדימה של מחיקת נתונים שנוצרו אוטומטית',
    applyGeneratedBtn: 'מחק נתונים שנוצרו אוטומטית במפות שנבחרו',
    previewResetBtn: 'תצוגה מקדימה של איפוס מלא',
    applyResetBtn: 'אפס את כל נתוני הניווט במפות שנבחרו',
    noSelection: 'יש לבחור לפחות מפה אחת.',
    previewTitleGenerated: 'מחיקת נתונים שנוצרו אוטומטית — תצוגה מקדימה',
    previewTitleReset: 'איפוס מלא של נתוני הניווט — תצוגה מקדימה',
    perMapGenerated: (name, points, edges) =>
      `${name}: ${points} נקודות שנוצרו אוטומטית, ${edges} חיבורים שנוצרו אוטומטית`,
    perMapReset: (name, points, edges) =>
      `${name}: ${points} נקודות, ${edges} חיבורים — כל נתוני הניווט של מפה זו`,
    totalsGenerated: (points, edges) =>
      `סה"כ במפות שנבחרו: ${points} נקודות שנוצרו אוטומטית, ${edges} חיבורים שנוצרו אוטומטית.`,
    totalsReset: (points, edges) =>
      `סה"כ במפות שנבחרו: ${points} נקודות ו-${edges} חיבורים יימחקו לצמיתות.`,
    resetWarning:
      'פעולה זו תמחק את כל נקודות וחיבורי המסלול — כולל כאלה שנוספו ידנית — בכל מפה שנבחרה. לא ניתן לבטל פעולה זו.',
    confirmPhraseInstructions: `הקלד/י בדיוק את הביטוי "${MULTI_RESET_PHRASE}" לאישור.`,
    confirmPhrasePlaceholder: MULTI_RESET_PHRASE,
    cancel: 'ביטול',
    confirmGenerated: 'מחק נתונים שנוצרו אוטומטית',
    confirmReset: 'מחק לצמיתות את כל נתוני הניווט',
    applying: 'מבצע…',
    applyFailed: 'פעולת הניקוי נכשלה',
    applySummaryGenerated: (points, edges, mapCount) =>
      `נמחקו ${points} נקודות ו-${edges} חיבורים שנוצרו אוטומטית ב-${mapCount} מפות.`,
    applySummaryReset: (points, edges, mapCount) =>
      `נמחקו ${points} נקודות ו-${edges} חיבורים ב-${mapCount} מפות.`,
  },
};

export default function AdminNavigationCleanupScreen() {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang] || UI.en;

  const [maps, setMaps] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selectedIds, setSelectedIds] = useState(() => new Set());

  const [generatedPreview, setGeneratedPreview] = useState(null);
  const [isGeneratedPreviewLoading, setIsGeneratedPreviewLoading] = useState(false);
  const [isGeneratedApplying, setIsGeneratedApplying] = useState(false);
  const [generatedError, setGeneratedError] = useState('');

  const [resetPreview, setResetPreview] = useState(null);
  const [isResetPreviewLoading, setIsResetPreviewLoading] = useState(false);
  const [isResetApplying, setIsResetApplying] = useState(false);
  const [resetError, setResetError] = useState('');
  const [resetPhrase, setResetPhrase] = useState('');

  const loadOverview = useCallback(async () => {
    setIsLoading(true);
    setLoadError('');
    try {
      const data = await getMapsNavigationOverview();
      setMaps(Array.isArray(data?.maps) ? data.maps : []);
    } catch (error) {
      console.error('Failed to load navigation cleanup overview:', error);
      setLoadError(resolveApiErrorMessage(error, { loadError: t.loadError }));
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const selectedMapIds = useMemo(() => Array.from(selectedIds), [selectedIds]);

  const toggleMap = (mapId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(mapId)) next.delete(mapId);
      else next.add(mapId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) =>
      prev.size === maps.length ? new Set() : new Set(maps.map((m) => m.map_id)),
    );
  };

  const handlePreviewGenerated = async () => {
    if (selectedMapIds.length === 0) {
      alert(t.noSelection);
      return;
    }
    setIsGeneratedPreviewLoading(true);
    setGeneratedError('');
    try {
      const preview = await previewMultiMapGeneratedCleanup(selectedMapIds);
      setGeneratedPreview(preview);
    } catch (error) {
      console.error('Failed to preview multi-map generated cleanup:', error);
      alert(resolveApiErrorMessage(error, { loadError: t.applyFailed }));
    } finally {
      setIsGeneratedPreviewLoading(false);
    }
  };

  const handleApplyGenerated = async () => {
    if (!generatedPreview) return;
    setIsGeneratedApplying(true);
    setGeneratedError('');
    try {
      const result = await applyMultiMapGeneratedCleanup(generatedPreview.valid_map_ids);
      setGeneratedPreview(null);
      await loadOverview();
      alert(
        t.applySummaryGenerated(
          result.total_points_deleted,
          result.total_edges_deleted,
          result.applied_map_ids.length,
        ),
      );
    } catch (error) {
      console.error('Failed to apply multi-map generated cleanup:', error);
      setGeneratedError(resolveApiErrorMessage(error, { loadError: t.applyFailed }));
    } finally {
      setIsGeneratedApplying(false);
    }
  };

  const handlePreviewReset = async () => {
    if (selectedMapIds.length === 0) {
      alert(t.noSelection);
      return;
    }
    setIsResetPreviewLoading(true);
    setResetError('');
    try {
      const preview = await previewMultiMapFullReset(selectedMapIds);
      setResetPreview(preview);
      setResetPhrase('');
    } catch (error) {
      console.error('Failed to preview multi-map full reset:', error);
      alert(resolveApiErrorMessage(error, { loadError: t.applyFailed }));
    } finally {
      setIsResetPreviewLoading(false);
    }
  };

  const handleApplyReset = async () => {
    if (!resetPreview) return;
    setIsResetApplying(true);
    setResetError('');
    try {
      const result = await applyMultiMapFullReset(resetPreview.valid_map_ids, {
        confirm: true,
        confirmationPhrase: resetPhrase,
      });
      setResetPreview(null);
      setResetPhrase('');
      await loadOverview();
      alert(
        t.applySummaryReset(
          result.total_points_deleted,
          result.total_edges_deleted,
          result.applied_map_ids.length,
        ),
      );
    } catch (error) {
      console.error('Failed to apply multi-map full reset:', error);
      setResetError(resolveApiErrorMessage(error, { loadError: t.applyFailed }));
    } finally {
      setIsResetApplying(false);
    }
  };

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="adm-inner-header">
          <div className="adm-topbar">
            <button
              className={`adm-back-btn${isRTL ? ' adm-back-btn-rtl' : ''}`}
              onClick={() => navigate('/screen/05')}
            >
              {t.back}
            </button>
            <div className="adm-lang-pill" role="group">
              {LANGUAGES.map((language) => (
                <button
                  key={language.code}
                  className={`adm-lang-btn${lang === language.code ? ' active' : ''}`}
                  onClick={() => setLang(language.code)}
                >
                  {language.label}
                </button>
              ))}
            </div>
          </div>
          <div className="adm-inner-heading">
            <h1 className="adm-inner-title">{t.title}</h1>
          </div>
        </div>

        <div className="adm-content">
          {loadError && (
            <div style={{ marginBottom: 16, padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
              {loadError}
            </div>
          )}

          <div className="adm-form-card" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
              <div style={{ fontWeight: 700, color: '#173b70' }}>
                {t.selectedCount(selectedMapIds.length)}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="adm-btn adm-btn-secondary"
                  onClick={handlePreviewGenerated}
                  disabled={isGeneratedPreviewLoading}
                >
                  {isGeneratedPreviewLoading ? t.loading : t.previewGeneratedBtn}
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handlePreviewReset}
                  disabled={isResetPreviewLoading}
                >
                  {isResetPreviewLoading ? t.loading : t.previewResetBtn}
                </button>
              </div>
            </div>

            {isLoading ? (
              <div style={{ padding: 20, textAlign: 'center', color: '#5f7fa6' }}>{t.loading}</div>
            ) : maps.length === 0 ? (
              <div style={{ padding: 20, textAlign: 'center', color: '#5f7fa6' }}>{t.empty}</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ textAlign: isRTL ? 'right' : 'left', borderBottom: '2px solid #e1ebf7' }}>
                      <th style={{ padding: 8 }}>
                        <input
                          type="checkbox"
                          checked={maps.length > 0 && selectedIds.size === maps.length}
                          onChange={toggleSelectAll}
                          aria-label={t.selectAll}
                        />
                      </th>
                      <th style={{ padding: 8 }}>{t.title.split(' (')[0]}</th>
                      <th style={{ padding: 8 }}>{t.colBuilding}</th>
                      <th style={{ padding: 8 }}>{t.colMapGroup}</th>
                      <th style={{ padding: 8 }}>{t.colFloor}</th>
                      <th style={{ padding: 8 }}>{t.colTotalPoints}</th>
                      <th style={{ padding: 8 }}>{t.colGenerated}</th>
                      <th style={{ padding: 8 }}>{t.colManual}</th>
                      <th style={{ padding: 8 }}>{t.colUnknown}</th>
                      <th style={{ padding: 8 }}>{t.colEdges}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {maps.map((mapItem) => (
                      <tr key={mapItem.map_id} style={{ borderBottom: '1px solid #eef3fa' }}>
                        <td style={{ padding: 8 }}>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(mapItem.map_id)}
                            onChange={() => toggleMap(mapItem.map_id)}
                          />
                        </td>
                        <td style={{ padding: 8, fontWeight: 600 }}>{mapItem.map_name}</td>
                        <td style={{ padding: 8 }}>{mapItem.building_name || '—'}</td>
                        <td style={{ padding: 8 }}>{mapItem.map_group_id || '—'}</td>
                        <td style={{ padding: 8 }}>{mapItem.floor ?? '—'}</td>
                        <td style={{ padding: 8 }}>{mapItem.total_point_count}</td>
                        <td style={{ padding: 8 }}>{mapItem.generated_point_count}</td>
                        <td style={{ padding: 8 }}>{mapItem.manual_point_count}</td>
                        <td style={{ padding: 8 }}>{mapItem.unknown_legacy_point_count}</td>
                        <td style={{ padding: 8 }}>{mapItem.total_edge_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Generated-only cleanup preview/confirm modal */}
        {generatedPreview && (
          <div
            onClick={() => setGeneratedPreview(null)}
            style={{ position: 'fixed', inset: 0, zIndex: 10030, background: 'rgba(9, 26, 53, 0.78)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{ width: 'min(560px, 96vw)', padding: 24, maxHeight: '90vh', overflowY: 'auto' }}
            >
              <div className="adm-form-card-title">{t.previewTitleGenerated}</div>

              <div style={{ fontSize: 13, color: '#4a6a8f', marginBottom: 14, lineHeight: 1.9, textAlign: isRTL ? 'right' : 'left' }}>
                {generatedPreview.per_map.map((entry) => (
                  <div key={entry.map_id}>
                    {t.perMapGenerated(entry.map_name || entry.map_id, entry.generated_point_count, entry.generated_edge_count)}
                  </div>
                ))}
              </div>

              <div style={{ fontSize: 13, fontWeight: 700, color: '#173b70', marginBottom: 14 }}>
                {t.totalsGenerated(generatedPreview.total_generated_point_count, generatedPreview.total_generated_edge_count)}
              </div>

              {generatedError && (
                <div style={{ fontSize: 12.5, color: '#c0392b', marginBottom: 14, fontWeight: 600 }}>{generatedError}</div>
              )}

              <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                <button type="button" className="adm-btn adm-btn-secondary" onClick={() => setGeneratedPreview(null)} disabled={isGeneratedApplying}>
                  {t.cancel}
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handleApplyGenerated}
                  disabled={isGeneratedApplying || generatedPreview.total_generated_point_count === 0}
                >
                  {isGeneratedApplying ? t.applying : t.confirmGenerated}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Full reset preview/confirm modal — requires the exact phrase */}
        {resetPreview && (
          <div
            onClick={() => setResetPreview(null)}
            style={{ position: 'fixed', inset: 0, zIndex: 10030, background: 'rgba(9, 26, 53, 0.78)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
          >
            <div
              className="adm-form-card"
              onClick={(event) => event.stopPropagation()}
              style={{ width: 'min(600px, 96vw)', padding: 24, maxHeight: '90vh', overflowY: 'auto' }}
            >
              <div className="adm-form-card-title">{t.previewTitleReset}</div>

              <div style={{ fontSize: 12.5, color: '#8a1f1f', background: '#fdecec', borderRadius: 8, padding: 12, marginBottom: 16, fontWeight: 600, lineHeight: 1.6, textAlign: isRTL ? 'right' : 'left' }}>
                {t.resetWarning}
              </div>

              <div style={{ fontSize: 13, color: '#4a6a8f', marginBottom: 14, lineHeight: 1.9, textAlign: isRTL ? 'right' : 'left' }}>
                {resetPreview.per_map.map((entry) => (
                  <div key={entry.map_id}>
                    {t.perMapReset(entry.map_name || entry.map_id, entry.total_point_count, entry.total_edge_count)}
                  </div>
                ))}
              </div>

              <div style={{ fontSize: 13, fontWeight: 700, color: '#173b70', marginBottom: 14 }}>
                {t.totalsReset(resetPreview.total_point_count, resetPreview.total_edge_count)}
              </div>

              <div style={{ fontSize: 12.5, color: '#173b70', fontWeight: 600, marginBottom: 8, textAlign: isRTL ? 'right' : 'left' }}>
                {t.confirmPhraseInstructions}
              </div>
              <input
                type="text"
                className="adm-input"
                value={resetPhrase}
                onChange={(event) => setResetPhrase(event.target.value)}
                placeholder={t.confirmPhrasePlaceholder}
                style={{ width: '100%', marginBottom: 14, boxSizing: 'border-box' }}
              />

              {resetError && (
                <div style={{ fontSize: 12.5, color: '#c0392b', marginBottom: 14, fontWeight: 600 }}>{resetError}</div>
              )}

              <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                <button type="button" className="adm-btn adm-btn-secondary" onClick={() => setResetPreview(null)} disabled={isResetApplying}>
                  {t.cancel}
                </button>
                <button
                  type="button"
                  className="adm-btn adm-btn-danger"
                  onClick={handleApplyReset}
                  disabled={
                    isResetApplying ||
                    resetPreview.total_point_count === 0 ||
                    resetPhrase.trim() !== MULTI_RESET_PHRASE
                  }
                >
                  {isResetApplying ? t.applying : t.confirmReset}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
