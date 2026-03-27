import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import '../styles/adminScreens.css';

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
    mapUploaded: 'Map image ready (simulated)',
    confirmDelete: 'Delete the current map?',
    yes: 'Yes, Delete',
    cancel: 'Cancel',
    form: {
      title: 'Edit Map Details',
      mapTitle: 'Map Title',
      campus: 'Campus / Location',
      address: 'Address',
      desc: 'Description',
      save: 'Save Changes',
    },
    details: { title: 'Title', campus: 'Campus', address: 'Address', desc: 'Description' },
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
    mapUploaded: 'صورة الخريطة جاهزة (محاكاة)',
    confirmDelete: 'حذف الخريطة الحالية؟',
    yes: 'نعم، احذف',
    cancel: 'إلغاء',
    form: {
      title: 'تعديل تفاصيل الخريطة',
      mapTitle: 'عنوان الخريطة',
      campus: 'الحرم / الموقع',
      address: 'العنوان',
      desc: 'الوصف',
      save: 'حفظ التغييرات',
    },
    details: { title: 'العنوان', campus: 'الحرم', address: 'العنوان', desc: 'الوصف' },
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
    mapUploaded: 'תמונת מפה מוכנה (דמי)',
    confirmDelete: 'למחוק את המפה הנוכחית?',
    yes: 'כן, מחק',
    cancel: 'ביטול',
    form: {
      title: 'עריכת פרטי מפה',
      mapTitle: 'כותרת מפה',
      campus: 'קמפוס / מיקום',
      address: 'כתובת',
      desc: 'תיאור',
      save: 'שמור שינויים',
    },
    details: { title: 'כותרת', campus: 'קמפוס', address: 'כתובת', desc: 'תיאור' },
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const MapIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <path d="M9 20L3 17V4l6 3M9 20l6-3M9 20V7M15 17l6 3V7l-6-3M15 17V4M9 7l6-3"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const UploadIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const EditIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const DeleteIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <polyline points="3 6 5 6 21 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

// ── AdminMapScreen ────────────────────────────────────────────────────────────
const AdminMapScreen = () => {
  const { lang, setLang } = useLang();
  const navigate          = useNavigate();
  const { mapData, updateMap } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t     = UI[lang];

  const [view,         setView]    = useState('detail'); // 'detail' | 'edit' | 'confirm-delete'
  const [form,         setForm]    = useState({});

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
    setView('detail');
  };

  const setField = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <div className="layout-wrapper">
      <div className="layout-shell adm-shell" dir={isRTL ? 'rtl' : 'ltr'}>

        {/* ── Header ──────────────────────────────────────────────────── */}
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
              {LANGUAGES.map((l) => (
                <button key={l.code}
                  className={`adm-lang-btn${lang === l.code ? ' active' : ''}`}
                  onClick={() => setLang(l.code)}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <div className="adm-inner-heading">
            <div className="adm-inner-icon"><MapIcon /></div>
            <h1 className="adm-inner-title">{t.title}</h1>
          </div>
        </div>

        {/* ── Content ─────────────────────────────────────────────────── */}
        <div className="adm-content">

          {/* ── Detail view ── */}
          {view === 'detail' && (
            <>
              {/* Map image preview placeholder */}
              <div className="adm-map-img-placeholder">
                {mapData.hasImage ? (
                  <>
                    <MapIcon />
                    <div className="adm-map-img-label">{t.mapUploaded}</div>
                  </>
                ) : (
                  <>
                    <MapIcon />
                    <div className="adm-map-img-label">{t.noMap}</div>
                  </>
                )}
              </div>

              {/* Upload / Replace button */}
              <button className="adm-upload-btn" onClick={handleUpload}>
                <UploadIcon />
                {mapData.hasImage ? t.replace : t.upload}
              </button>

              {/* Action buttons */}
              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-secondary" onClick={openEdit}>
                  <EditIcon /> {t.editDetails}
                </button>
                {mapData.hasImage && (
                  <button className="adm-btn adm-btn-danger" onClick={() => setView('confirm-delete')}>
                    <DeleteIcon /> {t.deleteMap}
                  </button>
                )}
              </div>

              {/* Current map details */}
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

          {/* ── Edit form ── */}
          {view === 'edit' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.form.title}</div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.mapTitle}</label>
                <input className="adm-form-input" value={form.title || ''}
                  onChange={(e) => setField('title', e.target.value)}
                  placeholder="e.g. Rabin Medical Center Campus" />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.campus}</label>
                <input className="adm-form-input" value={form.campus || ''}
                  onChange={(e) => setField('campus', e.target.value)}
                  placeholder="e.g. Main Campus — Petah Tikva" />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.address}</label>
                <input className="adm-form-input" value={form.address || ''}
                  onChange={(e) => setField('address', e.target.value)}
                  placeholder="Full address" />
              </div>
              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.desc}</label>
                <textarea className="adm-form-textarea" value={form.description || ''}
                  onChange={(e) => setField('description', e.target.value)}
                  placeholder="Brief description of the map…" />
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

          {/* ── Delete confirm ── */}
          {view === 'confirm-delete' && (
            <div className="adm-form-card" style={{ textAlign: 'center', padding: '28px 20px' }}>
              <div style={{ color: '#c0392b', marginBottom: 12 }}>
                <DeleteIcon />
              </div>
              <div style={{ fontFamily: 'var(--font-brand)', fontSize: 16, fontWeight: 700,
                color: '#1a3a6b', marginBottom: 8 }}>
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
      </div>
    </div>
  );
};

export default AdminMapScreen;
