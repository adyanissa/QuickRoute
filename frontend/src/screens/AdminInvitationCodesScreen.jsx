import { useEffect, useMemo, useState } from 'react';
import AdminScreenHeader from '../components/dashboard/AdminScreenHeader';
import { useLang } from '../context/LangContext';
import { useAdmin } from '../context/AdminContext';
import { useAuth } from '../context/AuthContext';
import {
  listInvitationCodes,
  createInvitationCode,
  revokeInvitationCode,
} from '../api/invitationCodesApi';
import {
  getAllowedRoleOptions,
  selectAssignedBuilding,
  requiresBuildingSelection,
  isSystemWideRole,
  resetScopeOnRoleChange,
  isCreateEnabled,
  resolveExpiresAt,
  buildCreateInvitationCodePayload,
  buildInvitationCodeSummary,
  getStatusLabel,
  canRevoke,
  getCopyableCode,
} from '../utils/invitationCodeFormHelpers';
import '../styles/adminScreens.css';

const LANGUAGES = [
  { code: 'ar', label: 'عربي' },
  { code: 'he', label: 'עברית' },
  { code: 'en', label: 'EN' },
];

const ROLE_LABELS = {
  en: {
    super_admin: 'Super Admin',
    global_manager: 'Global Manager',
    building_manager: 'Building Manager',
    regular_user: 'Regular User',
  },
  ar: {
    super_admin: 'مشرف عام',
    global_manager: 'مدير عام',
    building_manager: 'مدير مبنى',
    regular_user: 'مستخدم عادي',
  },
  he: {
    super_admin: 'מנהל-על',
    global_manager: 'מנהל גלובלי',
    building_manager: 'מנהל מבנה',
    regular_user: 'משתמש רגיל',
  },
};

const UI = {
  en: {
    title: 'Invitation Codes',
    back: 'Back',
    section: 'Signup Codes',
    addBtn: 'Add Invitation Code',
    empty: 'No invitation codes yet',
    emptyHint: 'Create one to let a new admin or user sign up with the right role and buildings',
    loading: 'Loading invitation codes...',
    count: (n) => `${n} code${n !== 1 ? 's' : ''}`,
    filters: { status: 'Status', role: 'Role', all: 'All' },
    statusOptions: { active: 'Active', used: 'Used', expired: 'Expired', revoked: 'Revoked' },
    form: {
      title: 'New Invitation Code',
      role: 'Role',
      selectRole: 'Select a role',
      responsibility: 'Responsibility',
      allBuildings: 'All Buildings',
      specificBuildings: 'Specific Buildings',
      systemWide: 'System-wide — no building selection needed',
      selectAtLeastOne: 'Select at least one building',
      noBuildings: 'No buildings exist yet',
      intendedEmail: 'Restrict to a specific email (optional)',
      intendedEmailHint: 'Only this email address will be able to use the code',
      expiration: 'Expiration',
      expNone: 'No expiration',
      exp24h: '24 hours',
      exp7d: '7 days',
      exp30d: '30 days',
      expCustom: 'Custom date',
      customCodeToggle: 'Use a custom code instead of auto-generating one',
      customCodePlaceholder: 'e.g. QR-WELCOME1',
      summary: 'Summary',
      summaryRole: 'Role',
      summaryResponsibility: 'Responsibility',
      summaryEmail: 'Restricted to',
      summaryExpiry: 'Expires',
      summaryNoExpiry: 'Never',
      summarySingleUse: 'Single use — the code stops working the moment it is used once',
      create: 'Create Code',
      cancel: 'Cancel',
    },
    result: {
      title: 'Invitation code created',
      copy: 'Copy Code',
      copied: 'Copied!',
      note: 'This code can only be used once. Share it with the invited person.',
      done: 'Done',
    },
    list: {
      role: 'Role',
      buildings: 'Buildings',
      allBuildings: 'All buildings',
      noBuildings: '—',
      email: 'Email',
      expires: 'Expires',
      never: 'Never',
      created: 'Created',
      by: 'by',
      used: 'Used',
      copy: 'Copy',
      copied: 'Copied',
      revoke: 'Revoke',
      confirmRevoke: 'Revoke this invitation code? It can no longer be used.',
      yes: 'Yes, Revoke',
      cancel: 'Cancel',
    },
    createError: 'Failed to create invitation code',
    revokeError: 'Failed to revoke invitation code',
    loadError: 'Failed to load invitation codes',
  },
  ar: {
    title: 'رموز الدعوة',
    back: 'رجوع',
    section: 'رموز التسجيل',
    addBtn: 'إضافة رمز دعوة',
    empty: 'لا توجد رموز دعوة بعد',
    emptyHint: 'أنشئ رمزًا للسماح لمشرف أو مستخدم جديد بالتسجيل بالدور والمباني الصحيحة',
    loading: 'جاري تحميل رموز الدعوة...',
    count: (n) => `${n} رمز`,
    filters: { status: 'الحالة', role: 'الدور', all: 'الكل' },
    statusOptions: { active: 'نشط', used: 'مستخدم', expired: 'منتهي', revoked: 'ملغى' },
    form: {
      title: 'رمز دعوة جديد',
      role: 'الدور',
      selectRole: 'اختر دورًا',
      responsibility: 'المسؤولية',
      allBuildings: 'كل المباني',
      specificBuildings: 'مبانٍ محددة',
      systemWide: 'على مستوى النظام — لا حاجة لاختيار مبنى',
      selectAtLeastOne: 'اختر مبنى واحدًا على الأقل',
      noBuildings: 'لا توجد مبانٍ بعد',
      intendedEmail: 'قصر على بريد إلكتروني محدد (اختياري)',
      intendedEmailHint: 'فقط هذا البريد الإلكتروني يمكنه استخدام الرمز',
      expiration: 'انتهاء الصلاحية',
      expNone: 'بدون انتهاء',
      exp24h: '24 ساعة',
      exp7d: '7 أيام',
      exp30d: '30 يومًا',
      expCustom: 'تاريخ مخصص',
      customCodeToggle: 'استخدم رمزًا مخصصًا بدلاً من التوليد التلقائي',
      customCodePlaceholder: 'مثال: QR-WELCOME1',
      summary: 'ملخص',
      summaryRole: 'الدور',
      summaryResponsibility: 'المسؤولية',
      summaryEmail: 'مقصور على',
      summaryExpiry: 'ينتهي في',
      summaryNoExpiry: 'أبدًا',
      summarySingleUse: 'استخدام واحد — يتوقف الرمز عن العمل بمجرد استخدامه مرة واحدة',
      create: 'إنشاء الرمز',
      cancel: 'إلغاء',
    },
    result: {
      title: 'تم إنشاء رمز الدعوة',
      copy: 'نسخ الرمز',
      copied: 'تم النسخ!',
      note: 'يمكن استخدام هذا الرمز مرة واحدة فقط. شاركه مع الشخص المدعو.',
      done: 'تم',
    },
    list: {
      role: 'الدور',
      buildings: 'المباني',
      allBuildings: 'كل المباني',
      noBuildings: '—',
      email: 'البريد الإلكتروني',
      expires: 'ينتهي',
      never: 'أبدًا',
      created: 'أُنشئ',
      by: 'بواسطة',
      used: 'استُخدم',
      copy: 'نسخ',
      copied: 'تم النسخ',
      revoke: 'إلغاء',
      confirmRevoke: 'إلغاء رمز الدعوة هذا؟ لن يمكن استخدامه بعد الآن.',
      yes: 'نعم، ألغِ',
      cancel: 'إلغاء',
    },
    createError: 'فشل إنشاء رمز الدعوة',
    revokeError: 'فشل إلغاء رمز الدعوة',
    loadError: 'فشل تحميل رموز الدعوة',
  },
  he: {
    title: 'קודי הזמנה',
    back: 'חזרה',
    section: 'קודי הרשמה',
    addBtn: 'הוסף קוד הזמנה',
    empty: 'אין עדיין קודי הזמנה',
    emptyHint: 'צור קוד כדי לאפשר למנהל או משתמש חדש להירשם עם התפקיד והמבנים הנכונים',
    loading: 'טוען קודי הזמנה...',
    count: (n) => `${n} קודים`,
    filters: { status: 'סטטוס', role: 'תפקיד', all: 'הכל' },
    statusOptions: { active: 'פעיל', used: 'בשימוש', expired: 'פג תוקף', revoked: 'בוטל' },
    form: {
      title: 'קוד הזמנה חדש',
      role: 'תפקיד',
      selectRole: 'בחר תפקיד',
      responsibility: 'אחריות',
      allBuildings: 'כל המבנים',
      specificBuildings: 'מבנים ספציפיים',
      systemWide: 'ברמת המערכת — אין צורך לבחור מבנה',
      selectAtLeastOne: 'בחר לפחות מבנה אחד',
      noBuildings: 'אין עדיין מבנים',
      intendedEmail: 'הגבל לאימייל מסוים (אופציונלי)',
      intendedEmailHint: 'רק כתובת אימייל זו תוכל להשתמש בקוד',
      expiration: 'תפוגה',
      expNone: 'ללא תפוגה',
      exp24h: '24 שעות',
      exp7d: '7 ימים',
      exp30d: '30 יום',
      expCustom: 'תאריך מותאם',
      customCodeToggle: 'השתמש בקוד מותאם במקום יצירה אוטומטית',
      customCodePlaceholder: 'לדוגמה: QR-WELCOME1',
      summary: 'סיכום',
      summaryRole: 'תפקיד',
      summaryResponsibility: 'אחריות',
      summaryEmail: 'מוגבל ל',
      summaryExpiry: 'פג תוקף',
      summaryNoExpiry: 'לעולם לא',
      summarySingleUse: 'שימוש חד פעמי — הקוד מפסיק לעבוד ברגע שנעשה בו שימוש',
      create: 'צור קוד',
      cancel: 'ביטול',
    },
    result: {
      title: 'קוד ההזמנה נוצר',
      copy: 'העתק קוד',
      copied: 'הועתק!',
      note: 'ניתן להשתמש בקוד זה פעם אחת בלבד. שתף אותו עם האדם המוזמן.',
      done: 'סיום',
    },
    list: {
      role: 'תפקיד',
      buildings: 'מבנים',
      allBuildings: 'כל המבנים',
      noBuildings: '—',
      email: 'אימייל',
      expires: 'פג תוקף',
      never: 'לעולם לא',
      created: 'נוצר',
      by: 'על ידי',
      used: 'בשימוש',
      copy: 'העתק',
      copied: 'הועתק',
      revoke: 'בטל',
      confirmRevoke: 'לבטל את קוד ההזמנה הזה? לא ניתן יהיה להשתמש בו יותר.',
      yes: 'כן, בטל',
      cancel: 'ביטול',
    },
    createError: 'יצירת קוד ההזמנה נכשלה',
    revokeError: 'ביטול קוד ההזמנה נכשל',
    loadError: 'טעינת קודי ההזמנה נכשלה',
  },
};

const BackArrow = ({ flip }) => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
    style={flip ? { transform: 'scaleX(-1)' } : undefined}>
    <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2.2"
      strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const KeyIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
    <circle cx="8" cy="15" r="4" stroke="currentColor" strokeWidth="1.8"/>
    <path d="M11 12l8-8M17 6l2 2M14 9l2 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const STATUS_TAG_CLASS = {
  active: 'adm-tag-green',
  used: 'adm-tag-blue',
  expired: 'adm-tag-orange',
  revoked: 'adm-tag-red',
};

const EXPIRATION_PRESETS = ['none', '24h', '7d', '30d', 'custom'];

const emptyForm = () => ({
  role: '',
  allBuildings: false,
  buildingIds: [],
  intendedEmail: '',
  expirationPreset: 'none',
  customExpiresAtLocal: '',
  useCustomCode: false,
  customCode: '',
});

const AdminInvitationCodesScreen = () => {
  const { lang } = useLang();
  const { user } = useAuth();
  const { buildings, loadBuildings } = useAdmin();

  const isRTL = lang === 'ar' || lang === 'he';
  const t = UI[lang];
  const roleLabels = ROLE_LABELS[lang];

  const [codes, setCodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [view, setView] = useState('list'); // 'list' | 'add' | 'created'
  const [createdCode, setCreatedCode] = useState(null);
  const [copiedId, setCopiedId] = useState(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState(null);

  const [statusFilter, setStatusFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');

  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);

  const allowedRoles = useMemo(() => getAllowedRoleOptions(user?.role), [user?.role]);

  const buildingsById = useMemo(
    () => Object.fromEntries(buildings.map((b) => [String(b.id), b])),
    [buildings]
  );

  const loadCodes = async () => {
    setLoading(true);
    setError('');
    try {
      const filters = {};
      if (statusFilter) filters.status = statusFilter;
      if (roleFilter) filters.role = roleFilter;
      const data = await listInvitationCodes(filters);
      setCodes(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load invitation codes:', err);
      setError(err.message || t.loadError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBuildings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadCodes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, roleFilter]);

  const openAdd = () => {
    setForm(emptyForm());
    setError('');
    setView('add');
  };

  const handleRoleChange = (newRole) => {
    setForm((prev) => resetScopeOnRoleChange(prev, newRole));
  };

  // Building Manager assignment is single-select — one building, in full.
  // Picking another building replaces the current choice instead of
  // accumulating a multi-building scope the backend would now reject.
  const toggleBuilding = (buildingId) => {
    setForm((prev) => selectAssignedBuilding(prev, buildingId));
  };

  const expiresAt = useMemo(
    () => resolveExpiresAt(form.expirationPreset, form.customExpiresAtLocal),
    [form.expirationPreset, form.customExpiresAtLocal]
  );

  const summary = useMemo(
    () => buildInvitationCodeSummary({ ...form, expiresAt }, buildingsById),
    [form, expiresAt, buildingsById]
  );

  const createEnabled = isCreateEnabled(form) && !submitting;

  const handleCreate = async () => {
    if (!isCreateEnabled(form)) return;

    setError('');
    setSubmitting(true);

    try {
      const payload = buildCreateInvitationCodePayload({
        ...form,
        expiresAt,
        customCode: form.useCustomCode ? form.customCode : '',
      });

      const created = await createInvitationCode(payload);
      setCreatedCode(created);
      setView('created');
      await loadCodes();
    } catch (err) {
      console.error('Failed to create invitation code:', err);
      setError(err.message || t.createError);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCopy = async (entry) => {
    const code = getCopyableCode(entry);
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(entry.id || 'created');
      setTimeout(() => setCopiedId(null), 1500);
    } catch (err) {
      console.error('Failed to copy invitation code:', err);
    }
  };

  const handleRevoke = async (id) => {
    setError('');
    try {
      await revokeInvitationCode(id);
      setConfirmRevokeId(null);
      await loadCodes();
    } catch (err) {
      console.error('Failed to revoke invitation code:', err);
      setError(err.message || t.revokeError);
      setConfirmRevokeId(null);
    }
  };

  const formatDate = (value) => {
    if (!value) return null;
    try {
      return new Date(value).toLocaleString(lang === 'ar' ? 'ar' : lang === 'he' ? 'he' : 'en');
    } catch {
      return value;
    }
  };

  return (
    <div className="qrd-page">
      <div className="qrd-pagebody" dir={isRTL ? 'rtl' : 'ltr'}>

        <div className="qrd-headwrap">
          <AdminScreenHeader
            pageKey="invitations"
            onBack={view !== 'list' ? () => setView('list') : undefined}
          />
        </div>

        <div className="adm-content">
          {error && (
            <div style={{ marginBottom: 16, padding: 12, borderRadius: 12, background: '#ffe9e9', color: '#a92323', fontSize: 14 }}>
              {error}
            </div>
          )}

          {view === 'list' && (
            <>
              <div className="adm-btn-row">
                <button className="adm-btn adm-btn-primary" onClick={openAdd}>
                  {t.addBtn}
                </button>
              </div>

              <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                <select className="adm-form-select" style={{ maxWidth: 180 }}
                  value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">{t.filters.status}: {t.filters.all}</option>
                  {Object.keys(t.statusOptions).map((s) => (
                    <option key={s} value={s}>{t.statusOptions[s]}</option>
                  ))}
                </select>
                <select className="adm-form-select" style={{ maxWidth: 180 }}
                  value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                  <option value="">{t.filters.role}: {t.filters.all}</option>
                  {Object.keys(roleLabels).map((r) => (
                    <option key={r} value={r}>{roleLabels[r]}</option>
                  ))}
                </select>
              </div>

              <div className="adm-section-row">
                <span className="adm-section-lbl">{t.section}</span>
                <span className="adm-section-count">{t.count(codes.length)}</span>
              </div>

              {loading ? (
                <div className="adm-empty"><div className="adm-empty-txt">{t.loading}</div></div>
              ) : codes.length === 0 ? (
                <div className="adm-empty">
                  <div className="adm-empty-icon"><KeyIcon /></div>
                  <div className="adm-empty-txt">{t.empty}</div>
                  <div className="adm-empty-hint">{t.emptyHint}</div>
                </div>
              ) : (
                <div className="adm-list">
                  {codes.map((entry) => (
                    <div key={entry.id} className="adm-list-item">
                      <div className="adm-list-item-row">
                        <div className="adm-list-item-info">
                          <div className="adm-list-item-name">
                            {entry.code}
                            <span className={`adm-tag ${STATUS_TAG_CLASS[entry.status] || 'adm-tag-blue'}`} style={{ marginLeft: 8 }}>
                              {getStatusLabel(entry.status)}
                            </span>
                          </div>
                          <div className="adm-list-item-meta">
                            <span className="adm-tag adm-tag-purple">{roleLabels[entry.role] || entry.role}</span>
                            <span className="adm-tag-txt">
                              {entry.all_buildings
                                ? t.list.allBuildings
                                : (entry.building_ids || []).map((id) => buildingsById[id]?.nameEn).filter(Boolean).join(', ') || t.list.noBuildings}
                            </span>
                          </div>
                          <div className="adm-list-item-meta">
                            {entry.intended_email && (
                              <span className="adm-tag-txt">{t.list.email}: {entry.intended_email}</span>
                            )}
                            <span className="adm-tag-txt">
                              {t.list.expires}: {formatDate(entry.expires_at) || t.list.never}
                            </span>
                          </div>
                          <div className="adm-list-item-meta">
                            <span className="adm-tag-txt">
                              {t.list.created} {formatDate(entry.created_at)}
                              {entry.created_by_name ? ` ${t.list.by} ${entry.created_by_name}` : ''}
                            </span>
                          </div>
                          {entry.status === 'used' && (
                            <div className="adm-list-item-meta">
                              <span className="adm-tag-txt">
                                {t.list.used} {formatDate(entry.used_at)}
                                {entry.used_by_email ? ` — ${entry.used_by_email}` : ''}
                              </span>
                            </div>
                          )}
                        </div>
                        <div className="adm-list-item-acts">
                          <button className="adm-icon-btn" onClick={() => handleCopy(entry)} title={t.list.copy}>
                            {copiedId === entry.id ? '✓' : '⧉'}
                          </button>
                          {canRevoke(entry) && (
                            <button className="adm-icon-btn adm-icon-btn-danger"
                              onClick={() => setConfirmRevokeId(confirmRevokeId === entry.id ? null : entry.id)}
                              title={t.list.revoke}>
                              ✕
                            </button>
                          )}
                        </div>
                      </div>

                      {confirmRevokeId === entry.id && (
                        <div className="adm-delete-strip">
                          <span className="adm-delete-strip-msg">{t.list.confirmRevoke}</span>
                          <div className="adm-delete-strip-acts">
                            <button className="adm-btn adm-btn-cancel" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => setConfirmRevokeId(null)}>
                              {t.list.cancel}
                            </button>
                            <button className="adm-btn adm-btn-confirm-delete" style={{ padding: '5px 12px', fontSize: 12 }} onClick={() => handleRevoke(entry.id)}>
                              {t.list.yes}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {view === 'add' && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.form.title}</div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.role}</label>
                <select className="adm-form-select" value={form.role}
                  onChange={(e) => handleRoleChange(e.target.value)}>
                  <option value="">{t.form.selectRole}</option>
                  {allowedRoles.map((r) => (
                    <option key={r} value={r}>{roleLabels[r]}</option>
                  ))}
                </select>
              </div>

              {form.role && (
                <div className="adm-form-group">
                  <label className="adm-form-label">{t.form.responsibility}</label>

                  {isSystemWideRole(form.role) ? (
                    <div className="adm-form-hint">{t.form.systemWide}</div>
                  ) : form.role === 'global_manager' ? (
                    <>
                      <div style={{ display: 'flex', gap: 14, marginBottom: 8 }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                          <input type="radio" checked={form.allBuildings}
                            onChange={() => setForm((p) => ({ ...p, allBuildings: true, buildingIds: [] }))} />
                          {t.form.allBuildings}
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                          <input type="radio" checked={!form.allBuildings}
                            onChange={() => setForm((p) => ({ ...p, allBuildings: false }))} />
                          {t.form.specificBuildings}
                        </label>
                      </div>
                      {!form.allBuildings && (
                        <BuildingChecklist
                          buildings={buildings}
                          selectedIds={form.buildingIds}
                          onToggle={toggleBuilding}
                          emptyLabel={t.form.noBuildings}
                        />
                      )}
                    </>
                  ) : requiresBuildingSelection(form.role) ? (
                    <BuildingChecklist
                      buildings={buildings}
                      selectedIds={form.buildingIds}
                      onToggle={toggleBuilding}
                      emptyLabel={t.form.noBuildings}
                    />
                  ) : null}

                  {requiresBuildingSelection(form.role) && form.buildingIds.length === 0 && (
                    <div className="adm-form-hint">{t.form.selectAtLeastOne}</div>
                  )}
                </div>
              )}

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.intendedEmail}</label>
                <input className="adm-form-input" type="email" value={form.intendedEmail}
                  onChange={(e) => setForm((p) => ({ ...p, intendedEmail: e.target.value }))}
                  placeholder="name@example.com" />
                <div className="adm-form-hint">{t.form.intendedEmailHint}</div>
              </div>

              <div className="adm-form-group">
                <label className="adm-form-label">{t.form.expiration}</label>
                <select className="adm-form-select" value={form.expirationPreset}
                  onChange={(e) => setForm((p) => ({ ...p, expirationPreset: e.target.value }))}>
                  <option value="none">{t.form.expNone}</option>
                  <option value="24h">{t.form.exp24h}</option>
                  <option value="7d">{t.form.exp7d}</option>
                  <option value="30d">{t.form.exp30d}</option>
                  <option value="custom">{t.form.expCustom}</option>
                </select>
                {form.expirationPreset === 'custom' && (
                  <input className="adm-form-input" type="datetime-local"
                    style={{ marginTop: 8 }}
                    value={form.customExpiresAtLocal}
                    onChange={(e) => setForm((p) => ({ ...p, customExpiresAtLocal: e.target.value }))} />
                )}
              </div>

              <div className="adm-form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
                  <input type="checkbox" checked={form.useCustomCode}
                    onChange={(e) => setForm((p) => ({ ...p, useCustomCode: e.target.checked }))} />
                  {t.form.customCodeToggle}
                </label>
                {form.useCustomCode && (
                  <input className="adm-form-input" style={{ marginTop: 8 }}
                    value={form.customCode}
                    onChange={(e) => setForm((p) => ({ ...p, customCode: e.target.value }))}
                    placeholder={t.form.customCodePlaceholder} />
                )}
              </div>

              {form.role && (
                <div className="adm-form-group" style={{ background: 'rgba(74,122,200,0.06)', borderRadius: 12, padding: 12 }}>
                  <div className="adm-form-label" style={{ marginBottom: 8 }}>{t.form.summary}</div>
                  <div style={{ fontSize: 13, lineHeight: 1.7 }}>
                    <div><strong>{t.form.summaryRole}:</strong> {roleLabels[summary.role] || summary.role}</div>
                    <div><strong>{t.form.summaryResponsibility}:</strong> {summary.responsibility}</div>
                    {summary.intendedEmail && (
                      <div><strong>{t.form.summaryEmail}:</strong> {summary.intendedEmail}</div>
                    )}
                    <div>
                      <strong>{t.form.summaryExpiry}:</strong>{' '}
                      {summary.expiresAt ? formatDate(summary.expiresAt) : t.form.summaryNoExpiry}
                    </div>
                    <div style={{ marginTop: 6, color: '#5a7aaa' }}>{t.form.summarySingleUse}</div>
                  </div>
                </div>
              )}

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>
                  {t.form.cancel}
                </button>
                <button className="adm-btn adm-btn-primary" onClick={handleCreate} disabled={!createEnabled}>
                  {t.form.create}
                </button>
              </div>
            </div>
          )}

          {view === 'created' && createdCode && (
            <div className="adm-form-card">
              <div className="adm-form-card-title">{t.result.title}</div>

              <div style={{
                textAlign: 'center', padding: '20px 12px', borderRadius: 12,
                background: 'rgba(42,170,138,0.08)', border: '1px solid rgba(42,170,138,0.22)',
                margin: '12px 0',
              }}>
                <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 1.5, color: '#1d7a5a' }}>
                  {createdCode.code}
                </div>
              </div>

              <div className="adm-form-hint" style={{ textAlign: 'center', marginBottom: 12 }}>
                {t.result.note}
              </div>

              <div className="adm-form-actions">
                <button className="adm-btn adm-btn-primary" onClick={() => handleCopy(createdCode)}>
                  {copiedId === (createdCode.id || 'created') ? t.result.copied : t.result.copy}
                </button>
                <button className="adm-btn adm-btn-cancel" onClick={() => setView('list')}>
                  {t.result.done}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const BuildingChecklist = ({ buildings, selectedIds, onToggle, emptyLabel }) => {
  if (!buildings.length) {
    return <div className="adm-form-hint">{emptyLabel}</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 180, overflowY: 'auto' }}>
      {buildings.map((b) => (
        <label key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={selectedIds.includes(String(b.id))}
            onChange={() => onToggle(String(b.id))} />
          {b.nameEn}
        </label>
      ))}
    </div>
  );
};

export default AdminInvitationCodesScreen;
