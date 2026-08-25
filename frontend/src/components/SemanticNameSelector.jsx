import { useEffect, useState } from 'react';
import { getPublishedSemanticEntitiesForMap } from '../api/mapAnalysisApi';
import { publishedEntityLabel } from '../utils/mapAnalysisHelpers';
import { matchesLocalizedSearch } from '../utils/localization';

// "Choose name from approved map data" (Section 16). Loads ONLY the
// active published semantic entities linked to the exact Map currently
// being worked on — never auto-creates a RoutePoint, never touches
// coordinates or edges. Selecting an entity just hands its resolved
// display name + semantic linkage ids back to the caller via onSelect;
// the caller (an Add Point / Edit RoutePoint form) decides what to do
// with them, exactly like typing a name manually.

const UI = {
  en: {
    label: 'Choose name from approved map data',
    empty: 'No approved semantic data for this Map.',
    loading: 'Loading…',
    placeholder: 'Search…',
  },
  ar: {
    label: 'اختر اسمًا من البيانات الدلالية المعتمدة',
    empty: 'لا توجد بيانات دلالية معتمدة لهذه الخريطة.',
    loading: 'جارٍ التحميل…',
    placeholder: 'بحث…',
  },
  he: {
    label: 'בחר שם מנתונים סמנטיים מאושרים',
    empty: 'אין נתונים סמנטיים מאושרים למפה זו.',
    loading: 'טוען…',
    placeholder: 'חיפוש…',
  },
};

export default function SemanticNameSelector({ mapId, lang = 'en', onSelect }) {
  const t = UI[lang] || UI.en;
  const [entities, setEntities] = useState([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!mapId || !open) return;
    let cancelled = false;
    setLoading(true);
    getPublishedSemanticEntitiesForMap(mapId)
      .then((list) => { if (!cancelled) setEntities(list); })
      .catch(() => { if (!cancelled) setEntities([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [mapId, open]);

  if (!mapId) return null;

  // Findable by ANY stored translation (Section 10), not just whichever
  // one is currently displayed for `lang` — same shared search helper
  // DestinationSelectionScreen.jsx uses, never a second, independently
  // drifting substring-match implementation.
  const filtered = entities.filter((entity) =>
    matchesLocalizedSearch(entity.names, entity.names?.original, query),
  );

  return (
    <div className="adm-form-group" style={{ marginTop: 4 }}>
      <button
        type="button"
        className="adm-btn adm-btn-secondary"
        style={{ fontSize: 12, padding: '4px 10px' }}
        onClick={() => setOpen((v) => !v)}
      >
        {t.label}
      </button>

      {open && (
        <div style={{ marginTop: 6, border: '1px solid #dbe4f0', borderRadius: 8, padding: 8, maxHeight: 220, overflowY: 'auto' }}>
          <input
            className="adm-form-input"
            style={{ fontSize: 12, marginBottom: 6 }}
            placeholder={t.placeholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {loading && <div style={{ fontSize: 12, color: '#6c7a8c' }}>{t.loading}</div>}
          {!loading && filtered.length === 0 && (
            <div style={{ fontSize: 12, color: '#6c7a8c' }}>{t.empty}</div>
          )}
          {!loading && filtered.map((entity) => (
            <div
              key={`${entity.publicationId}-${entity.entityExternalId}`}
              role="button"
              tabIndex={0}
              style={{ padding: '4px 6px', fontSize: 12.5, cursor: 'pointer', borderRadius: 6 }}
              onClick={() => {
                onSelect?.({
                  displayName: publishedEntityLabel(entity, lang),
                  displayNameEn: entity.names.en,
                  displayNameAr: entity.names.ar,
                  displayNameHe: entity.names.he,
                  semanticPublicationId: entity.publicationId,
                  semanticEntityExternalId: entity.entityExternalId,
                  semanticEntityType: entity.entityType,
                });
                setOpen(false);
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = '#eef4ff'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              {publishedEntityLabel(entity, lang)}
              {entity.category && (
                <span style={{ color: '#8a99ad', marginInlineStart: 6 }}>({entity.category})</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
