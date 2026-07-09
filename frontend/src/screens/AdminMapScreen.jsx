import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import '../styles/adminScreens.css';

const API_BASE_URL = 'http://127.0.0.1:8000';
const CURRENT_MAP_ID = '6a4cf16aa921ae9dc1c84616';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const UI = {
  en: {
    title: 'Map Management',
    back: 'Back',
    upload: 'Upload Map Image',
    replace: 'Replace Map',
    editDetails: 'Edit Details',
    deleteMap: 'Delete Map',
    currentMap: 'Current Map',
    noMap: 'No map uploaded yet',
    noMapHint: 'Upload a floor plan image to get started',
    confirmDelete: 'Delete the current map?',
    yes: 'Yes, Delete',
    cancel: 'Cancel',
    addPoint: 'Add Route Point',
    savePoint: 'Save Route Point',
    savedPoint: 'Route point saved',
    openFullMap: 'Click map to open full view',
    selectPoint: 'Click on the map to select a route point',
    pointName: 'Point Name',
    pointType: 'Point Type',
    floor: 'Floor',
    form: {
      title: 'Edit Map Details',
      mapTitle: 'Map Title',
      campus: 'Campus / Location',
      address: 'Address',
      desc: 'Description',
      save: 'Save Changes',
    },
    details: {
      title: 'Title',
      campus: 'Campus',
      address: 'Address',
      desc: 'Description',
    },
  },
  ar: {
    title: 'إدارة الخريطة',
    back: 'رجوع',
    upload: 'تحميل صورة الخريطة',
    replace: 'استبدال الخريطة',
    editDetails: 'تعديل التفاصيل',
    deleteMap: 'حذف الخريطة',
    currentMap: 'الخريطة الحالية',
    noMap: 'لم يتم تحميل أي خريطة',
    noMapHint: 'حمّل صورة مخطط للبدء',
    confirmDelete: 'حذف الخريطة الحالية؟',
    yes: 'نعم، احذف',
    cancel: 'إلغاء',
    addPoint: 'إضافة نقطة مسار',
    savePoint: 'حفظ نقطة المسار',
    savedPoint: 'تم حفظ نقطة المسار',
    openFullMap: 'اضغطي على الخريطة لفتحها كاملة',
    selectPoint: 'اضغطي على الخريطة لاختيار نقطة مسار',
    pointName: 'اسم النقطة',
    pointType: 'نوع النقطة',
    floor: 'الطابق',
    form: {
      title: 'تعديل تفاصيل الخريطة',
      mapTitle: 'عنوان الخريطة',
      campus: 'الحرم / الموقع',
      address: 'العنوان',
      desc: 'الوصف',
      save: 'حفظ التغييرات',
    },
    details: {
      title: 'العنوان',
      campus: 'الحرم',
      address: 'العنوان',
      desc: 'الوصف',
    },
  },
  he: {
    title: 'ניהול מפה',
    back: 'חזרה',
    upload: 'העלה תמונת מפה',
    replace: 'החלף מפה',
    editDetails: 'ערוך פרטים',
    deleteMap: 'מחק מפה',
    currentMap: 'מפה נוכחית',
    noMap: 'לא הועלתה מפה עדיין',
    noMapHint: 'העלה תוכנית קומה להתחלה',
    confirmDelete: 'למחוק את המפה הנוכחית?',
    yes: 'כן, מחק',
    cancel: 'ביטול',
    addPoint: 'הוסף נקודת מסלול',
    savePoint: 'שמור נקודת מסלול',
    savedPoint: 'נקודת המסלול נשמרה',
    openFullMap: 'לחצי על המפה כדי לפתוח תצוגה מלאה',
    selectPoint: 'לחצי על המפה כדי לבחור נקודת מסלול',
    pointName: 'שם הנקודה',
    pointType: 'סוג הנקודה',
    floor: 'קומה',
    form: {
      title: 'עריכת פרטי מפה',
      mapTitle: 'כותרת מפה',
      campus: 'קמפוס / מיקום',
      address: 'כתובת',
      desc: 'תיאור',
      save: 'שמור שינויים',
    },
    details: {
      title: 'כותרת',
      campus: 'קמפוס',
      address: 'כתובת',
      desc: 'תיאור',
    },
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline points="3 6 5 6 21 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const AdminMapScreen = () => {
  const { lang, setLang } = useLang();
  const navigate = useNavigate();
  const { mapData, updateMap } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];

  const [view, setView] = useState('detail');
  const [form, setForm] = useState({});
  const [isMapOpen, setIsMapOpen] = useState(false);

  const [clickedPoint, setClickedPoint] = useState(null);
  const [pointName, setPointName] = useState('');
  const [pointType, setPointType] = useState('hallway');
  const [floor, setFloor] = useState(0);

  const openEdit = () => {
    setForm({ ...mapData });
    setView('edit');
  };

  const handleSave = () => {
    updateMap({ ...form });
    setView('detail');
  };

  const handleUpload = () => {
    updateMap({ ...mapData, hasImage: true });
  };

  const handleDelete = () => {
    updateMap({ ...mapData, hasImage: false, imageUrl: null });
    setClickedPoint(null);
    setIsMapOpen(false);
    setView('detail');
  };

  const setField = (key, value) => {
    setForm((previousForm) => ({ ...previousForm, [key]: value }));
  };

  const handleFullMapClick = (event) => {
    const img = event.currentTarget;
    const rect = img.getBoundingClientRect();

    const displayX = event.clientX - rect.left;
    const displayY = event.clientY - rect.top;

    const scaleX = img.naturalWidth / rect.width;
    const scaleY = img.naturalHeight / rect.height;

    const x = Math.round(displayX * scaleX);
    const y = Math.round(displayY * scaleY);

    setClickedPoint({
      x,
      y,
      displayX,
      displayY,
      displayWidth: rect.width,
      displayHeight: rect.height,
    });

    setPointName(`Point ${x},${y}`);
  };

  const saveRoutePoint = async () => {
    if (!clickedPoint || !pointName.trim()) return;

    const payload = {
      map_id: CURRENT_MAP_ID,
      name: pointName.trim(),
      point_type: pointType,
      x: clickedPoint.x,
      y: clickedPoint.y,
      floor: Number(floor),
      building_id: null,
      room_id: null,
      is_accessible: true,
    };

    try {
      const response = await fetch(`${API_BASE_URL}/api/route-points`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error(errorText);
        alert('Failed to save route point');
        return;
      }

      alert(t.savedPoint);
      setClickedPoint(null);
      setPointName('');
      setPointType('hallway');
      setFloor(0);
      setIsMapOpen(false);
    } catch (error) {
      console.error(error);
      alert('Failed to connect to backend');
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
              <BackArrow flip={isRTL} />
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
            <div className="adm-inner-icon">
              <MapIcon />
            </div>
            <h1 className="adm-inner-title">{t.title}</h1>
          </div>
        </div>

        <div className="adm-content">
          {view === 'detail' && (
            <>
              <div className="adm-map-img-placeholder">
                {mapData.hasImage && mapData.imageUrl ? (
                  <>
                    <img
                      src={mapData.imageUrl}
                      alt={mapData.title || 'Current map'}
                      onClick={() => setIsMapOpen(true)}
                      style={{
                        display: 'block',
                        width: '100%',
                        maxHeight: '520px',
                        objectFit: 'contain',
                        borderRadius: '18px',
                        cursor: 'zoom-in',
                      }}
                    />

                    <div style={{ marginTop: 10, fontSize: 12, fontWeight: 700, color: '#4c7bb5' }}>
                      {t.openFullMap}
                    </div>
                  </>
                ) : (
                  <>
                    <MapIcon />
                    <div className="adm-map-img-label">{t.noMap}</div>
                    <div style={{ marginTop: '6px', fontSize: '12px', color: '#7a9abf' }}>
                      {t.noMapHint}
                    </div>
                  </>
                )}
              </div>

              <button className="adm-upload-btn" onClick={handleUpload}>
                <UploadIcon />
                {mapData.hasImage ? t.replace : t.upload}
              </button>

              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-secondary" onClick={openEdit}>
                  <EditIcon />
                  {t.editDetails}
                </button>

                {mapData.hasImage && (
                  <button className="adm-btn adm-btn-danger" onClick={() => setView('confirm-delete')}>
                    <DeleteIcon />
                    {t.deleteMap}
                  </button>
                )}
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.currentMap}</span>
              </div>

              <div className="adm-form-card">
                <div className="adm-detail-list">
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">{t.details.title}</span>
                    <span className="adm-detail-val">{mapData.title || '—'}</span>
                  </div>
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">{t.details.campus}</span>
                    <span className="adm-detail-val">{mapData.campus || '—'}</span>
                  </div>
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">{t.details.address}</span>
                    <span className="adm-detail-val">{mapData.address || '—'}</span>
                  </div>
                  <div className="adm-detail-row">
                    <span className="adm-detail-key">{t.details.desc}</span>
                    <span className="adm-detail-val">{mapData.description || '—'}</span>
                  </div>
                </div>
              </div>
            </>
          )}

          {view === 'edit' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.form.title}</div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.mapTitle}</label>
                <input
                  className="adm-form-input"
                  value={form.title || ''}
                  onChange={(event) => setField('title', event.target.value)}
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.campus}</label>
                <input
                  className="adm-form-input"
                  value={form.campus || ''}
                  onChange={(event) => setField('campus', event.target.value)}
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.address}</label>
                <input
                  className="adm-form-input"
                  value={form.address || ''}
                  onChange={(event) => setField('address', event.target.value)}
                />
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.desc}</label>
                <textarea
                  className="adm-form-textarea"
                  value={form.description || ''}
                  onChange={(event) => setField('description', event.target.value)}
                />
              </div>

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('detail')}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={handleSave}>
                  {t.form.save}
                </button>
              </div>
            </div>
          )}

          {view === 'confirm-delete' && (
            <div className="adm-form-card" style={{ textAlign: 'center', padding: '28px 20px' }}>
              <div style={{ color: '#c0392b', marginBottom: 12 }}>
                <DeleteIcon />
              </div>

              <div style={{ fontFamily: 'var(--font-brand)', fontSize: 16, fontWeight: 700, color: '#1a3a6b', marginBottom: 8 }}>
                {t.confirmDelete}
              </div>

              <div style={{ fontSize: 12.5, color: '#7a9abf', marginBottom: 20, lineHeight: 1.5 }}>
                {mapData.title}
              </div>

              <div className="adm-form-actions" style={{ justifyContent: 'center' }}>
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('detail')}>
                  {t.cancel}
                </button>
                <button className="adm-btn adm-btn-confirm-delete" onClick={handleDelete}>
                  {t.yes}
                </button>
              </div>
            </div>
          )}
        </div>

        {isMapOpen && (
          <div
            onClick={() => setIsMapOpen(false)}
            style={{
              position: 'fixed',
              inset: 0,
              background: 'rgba(0,0,0,0.82)',
              zIndex: 9999,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 24,
            }}
          >
            <div
              onClick={(event) => event.stopPropagation()}
              style={{
                position: 'relative',
                maxWidth: '96vw',
                maxHeight: '90vh',
              }}
            >
              <img
                src={mapData.imageUrl}
                alt={mapData.title || 'Full map'}
                onClick={handleFullMapClick}
                style={{
                  display: 'block',
                  maxWidth: '96vw',
                  maxHeight: '90vh',
                  objectFit: 'contain',
                  borderRadius: 14,
                  background: 'white',
                  cursor: 'crosshair',
                }}
              />

              {clickedPoint && (
                <div
                  style={{
                    position: 'absolute',
                    left: clickedPoint.displayX - 7,
                    top: clickedPoint.displayY - 7,
                    width: 14,
                    height: 14,
                    borderRadius: '50%',
                    background: 'red',
                    border: '2px solid white',
                    boxShadow: '0 0 8px rgba(0,0,0,0.5)',
                    pointerEvents: 'none',
                  }}
                />
              )}

              <div
                style={{
                  position: 'absolute',
                  left: '50%',
                  bottom: 18,
                  transform: 'translateX(-50%)',
                  background: 'rgba(20, 55, 105, 0.92)',
                  color: 'white',
                  padding: '10px 16px',
                  borderRadius: 999,
                  fontSize: 13,
                  fontWeight: 700,
                  pointerEvents: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                {t.selectPoint}
              </div>

              {clickedPoint && (
                <div
                  style={{
                    position: 'absolute',
                    top: 20,
                    left: 20,
                    width: 300,
                    background: 'white',
                    borderRadius: 16,
                    padding: 16,
                    boxShadow: '0 14px 40px rgba(0,0,0,0.35)',
                  }}
                >
                  <div style={{ fontWeight: 800, color: '#173b70', marginBottom: 10 }}>
                    {t.addPoint}
                  </div>

                  <div style={{ fontWeight: 700, color: '#173b70', marginBottom: 10 }}>
                    X: {clickedPoint.x} | Y: {clickedPoint.y}
                  </div>

                  <div className="adm-form-group">
                    <label className="adm-form-label">{t.pointName}</label>
                    <input
                      className="adm-form-input"
                      value={pointName}
                      onChange={(e) => setPointName(e.target.value)}
                    />
                  </div>

                  <div className="adm-form-group">
                    <label className="adm-form-label">{t.pointType}</label>
                    <select
                      className="adm-form-input"
                      value={pointType}
                      onChange={(e) => setPointType(e.target.value)}
                    >
                      <option value="entrance">entrance</option>
                      <option value="hallway">hallway</option>
                      <option value="stairs">stairs</option>
                      <option value="elevator">elevator</option>
                      <option value="room">room</option>
                    </select>
                  </div>

                  <div className="adm-form-group">
                    <label className="adm-form-label">{t.floor}</label>
                    <input
                      className="adm-form-input"
                      type="number"
                      value={floor}
                      onChange={(e) => setFloor(e.target.value)}
                    />
                  </div>

                  <div className="adm-form-actions">
                    <button
                      className="adm-btn adm-btn-cancel"
                      onClick={() => {
                        setClickedPoint(null);
                        setPointName('');
                      }}
                    >
                      {t.cancel}
                    </button>

                    <button className="adm-btn adm-btn-primary" onClick={saveRoutePoint}>
                      {t.savePoint}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <button
              onClick={() => setIsMapOpen(false)}
              style={{
                position: 'absolute',
                top: 24,
                right: 24,
                width: 50,
                height: 50,
                border: 'none',
                borderRadius: '50%',
                cursor: 'pointer',
                fontSize: 28,
                background: 'white',
                color: '#173b70',
              }}
            >
              ×
            </button>
          </div>
        )}

      </div>
    </div>
  );
};

export default AdminMapScreen;