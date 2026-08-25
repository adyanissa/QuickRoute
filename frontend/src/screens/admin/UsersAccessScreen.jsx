import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLang } from '../../context/LangContext';
import { useAdmin } from '../../context/AdminContext';
import { useAuth } from '../../context/AuthContext';
import {
  getAdminUsers,
  updateAdminUser,
  deleteAdminUser,
} from '../../api/usersApi';
import { getAssignableRoles } from '../../utils/dashboardPermissions';
import { buildingDisplayName, resolveSiteName } from '../../utils/dashboardModel';
import AdminScreenHeader from '../../components/dashboard/AdminScreenHeader';
import { StatePanel } from '../../components/dashboard/DashboardCards';
import dashboardUi from '../dashboards/dashboardUi';
import '../../styles/usersAccess.css';

// Users & Access — administrator account management, rendered inside the
// same shared admin shell as every other page (AdminLayout supplies the
// sidebar, branding, language selector and identity header; this screen
// only supplies its own content and the shared AdminScreenHeader).
//
// Authorization is the backend's: GET/PUT/DELETE /api/admin/users are
// super_admin/global_manager-only and re-check the role hierarchy on
// every mutation. This screen additionally never OFFERS an action the
// backend would refuse — it reads `can_edit`/`can_delete` off each record
// (decided server-side) rather than re-deriving the hierarchy here, so a
// super_admin row is simply not actionable for a global_manager.
//
// Nothing on this page renders a raw ObjectId as a person's
// responsibility: the backend resolves the assigned building's real name
// and site, and this screen falls back to an honest description of a
// legacy scope shape rather than inventing one.

const ROLE_FILTERS = ['super_admin', 'global_manager', 'building_manager'];

const DotsIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" />
    <circle cx="12" cy="12" r="1.8" />
    <circle cx="19" cy="12" r="1.8" />
  </svg>
);

const UsersAccessScreen = () => {
  const { lang } = useLang();
  const { user } = useAuth();
  const { buildings } = useAdmin();

  const t = dashboardUi[lang] || dashboardUi.en;
  const ui = t.usersAccess;
  const isRTL = t.dir === 'rtl';

  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [menuFor, setMenuFor] = useState(null);
  const [editing, setEditing] = useState(null);
  const [deleting, setDeleting] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await getAdminUsers();
      setRecords(Array.isArray(data) ? data : []);
      setError('');
    } catch (err) {
      console.error('Failed to load administrators:', err);
      setError(err.message || ui.loadError);
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [ui.loadError]);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Search/filter run on the already-loaded page rather than as a request
  // per keystroke; the API supports both and this keeps typing instant.
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return records.filter((record) => {
      if (roleFilter && record.role !== roleFilter) return false;
      if (!needle) return true;
      return (
        (record.full_name || '').toLowerCase().includes(needle) ||
        (record.email || '').toLowerCase().includes(needle)
      );
    });
  }, [records, search, roleFilter]);

  const describeResponsibility = (record) => {
    if (record.role === 'building_manager' && record.assigned_building) {
      const site = record.assigned_building.site;
      return site
        ? `${site} · ${record.assigned_building.name}`
        : record.assigned_building.name;
    }
    return ui.scope[record.scope_kind] || ui.scope.none;
  };

  const handleSave = async (draft) => {
    const changes = { full_name: draft.fullName, role: draft.role };
    if (draft.role === 'building_manager') changes.building_id = draft.buildingId;

    const saved = await updateAdminUser(draft.id, changes);
    setRecords((prev) => prev.map((r) => (r.id === saved.id ? saved : r)));
    setEditing(null);
  };

  const handleDelete = async (record) => {
    await deleteAdminUser(record.id);
    setRecords((prev) => prev.filter((r) => r.id !== record.id));
    setDeleting(null);
  };

  return (
    <>
      <AdminScreenHeader pageKey="users" />

      {/* No SectionHead here: AdminScreenHeader already renders this
          page's title and description from the same dictionary entry, and
          repeating it produced the heading twice. */}
      <section className="qrd-section qra-page-tail" style={{ marginBlockStart: 0 }}>
        <div className="qra-toolbar">
          <input
            className="qra-search"
            type="search"
            value={search}
            placeholder={ui.searchPlaceholder}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="qra-select"
            value={roleFilter}
            onChange={(event) => setRoleFilter(event.target.value)}
          >
            <option value="">{ui.roleAll}</option>
            {ROLE_FILTERS.map((role) => (
              <option key={role} value={role}>
                {t.roles[role]}
              </option>
            ))}
          </select>
        </div>

        {error && <div className="qrd-alert" role="alert">{error}</div>}

        {loading ? (
          <StatePanel title={t.states.loading} />
        ) : visible.length === 0 ? (
          <StatePanel title={ui.empty} hint={records.length === 0 ? ui.emptyHint : undefined} />
        ) : (
          <div className="qra-table" role="table">
            <div className="qra-row qra-head" role="row">
              <span role="columnheader">{ui.colName}</span>
              <span role="columnheader">{ui.colEmail}</span>
              <span role="columnheader">{ui.colRole}</span>
              <span role="columnheader">{ui.colResponsibility}</span>
              <span role="columnheader" aria-label={ui.edit} />
            </div>

            {visible.map((record) => (
              <div className="qra-row" role="row" key={record.id}>
                <span className="qra-name" role="cell" data-label={ui.colName}>
                  {record.full_name}
                  {record.id === user?.id && <span className="qra-you">•</span>}
                </span>
                <span className="qra-email" role="cell" data-label={ui.colEmail}>
                  {record.email}
                </span>
                <span role="cell" data-label={ui.colRole}>
                  <span className={`qra-role is-${record.role}`}>{t.roles[record.role]}</span>
                </span>
                <span className="qra-scope" role="cell" data-label={ui.colResponsibility}>
                  {describeResponsibility(record)}
                </span>
                <span className="qra-actions" role="cell">
                  {(record.can_edit || record.can_delete) && (
                    <button
                      type="button"
                      className="qra-menu-btn"
                      aria-haspopup="menu"
                      aria-expanded={menuFor === record.id}
                      onClick={() => setMenuFor(menuFor === record.id ? null : record.id)}
                    >
                      <DotsIcon />
                    </button>
                  )}
                  {menuFor === record.id && (
                    <div className="qra-menu" role="menu">
                      {record.can_edit && (
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setMenuFor(null);
                            setEditing(record);
                          }}
                        >
                          {ui.edit}
                        </button>
                      )}
                      {record.can_delete && (
                        <button
                          type="button"
                          role="menuitem"
                          className="is-destructive"
                          onClick={() => {
                            setMenuFor(null);
                            setDeleting(record);
                          }}
                        >
                          {ui.delete}
                        </button>
                      )}
                    </div>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {editing && (
        <EditUserDialog
          record={editing}
          actor={user}
          buildings={buildings}
          ui={ui}
          roleLabels={t.roles}
          unassignedSiteLabel={t.labels.unassignedSite}
          isRTL={isRTL}
          onCancel={() => setEditing(null)}
          onSave={handleSave}
        />
      )}

      {deleting && (
        <ConfirmDeleteDialog
          record={deleting}
          ui={ui}
          isRTL={isRTL}
          onCancel={() => setDeleting(null)}
          onConfirm={handleDelete}
        />
      )}
    </>
  );
};

// ── Edit ────────────────────────────────────────────────────────────────
// Only Full Name, Role and (for a Building Manager) the assigned Building
// are editable. Email is the authentication identifier and has no
// re-verification flow in the current architecture, so it is deliberately
// read-only here; passwords are never sent to or from this screen at all.

const EditUserDialog = ({
  record,
  actor,
  buildings,
  ui,
  roleLabels,
  unassignedSiteLabel,
  isRTL,
  onCancel,
  onSave,
}) => {
  const [fullName, setFullName] = useState(record.full_name || '');
  const [role, setRole] = useState(record.role);
  const [buildingId, setBuildingId] = useState((record.building_ids || [])[0] || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Mirrors the backend's assignable-role table, so the dropdown cannot
  // offer a promotion the API would reject (a global_manager never sees
  // super_admin here). The role the account already holds stays listed so
  // an unrelated edit does not silently demote it.
  const roleOptions = useMemo(() => {
    const allowed = getAssignableRoles(actor);
    return allowed.includes(record.role) ? allowed : [record.role, ...allowed];
  }, [actor, record.role]);

  const buildingOptions = useMemo(
    () =>
      [...buildings].sort((a, b) =>
        buildingDisplayName(a).localeCompare(buildingDisplayName(b)),
      ),
    [buildings],
  );

  const needsBuilding = role === 'building_manager';
  const canSubmit =
    fullName.trim().length >= 2 && (!needsBuilding || Boolean(buildingId)) && !saving;

  const submit = async () => {
    setSaving(true);
    setError('');
    try {
      await onSave({ id: record.id, fullName: fullName.trim(), role, buildingId });
    } catch (err) {
      console.error('Failed to save user:', err);
      setError(err.message || ui.saveError);
      setSaving(false);
    }
  };

  return (
    <div className="qra-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="qra-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={ui.editTitle}
        dir={isRTL ? 'rtl' : 'ltr'}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="qra-dialog-title">{ui.editTitle}</h2>

        <label className="qra-field">
          <span className="qra-label">{ui.fullName}</span>
          <input
            className="qra-input"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
        </label>

        <label className="qra-field">
          <span className="qra-label">{ui.role}</span>
          <select
            className="qra-input"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {roleOptions.map((option) => (
              <option key={option} value={option}>
                {roleLabels[option] || option}
              </option>
            ))}
          </select>
        </label>

        {/* Shown only for the one role that actually has a building
            assignment — no irrelevant control for the others. */}
        {needsBuilding && (
          <label className="qra-field">
            <span className="qra-label">{ui.assignedBuilding}</span>
            <select
              className="qra-input"
              value={buildingId}
              onChange={(event) => setBuildingId(event.target.value)}
            >
              <option value="">{ui.selectBuilding}</option>
              {buildingOptions.map((building) => (
                <option key={building.id} value={building.id}>
                  {`${resolveSiteName(building, unassignedSiteLabel)} — ${buildingDisplayName(building)}`}
                </option>
              ))}
            </select>
          </label>
        )}

        {error && <div className="qrd-alert" role="alert">{error}</div>}

        <div className="qra-dialog-actions">
          <button type="button" className="qrd-btn is-ghost" onClick={onCancel}>
            {ui.cancel}
          </button>
          <button type="button" className="qrd-btn" disabled={!canSubmit} onClick={submit}>
            {saving ? ui.saving : ui.save}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Delete ──────────────────────────────────────────────────────────────

const ConfirmDeleteDialog = ({ record, ui, isRTL, onCancel, onConfirm }) => {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');

  const confirm = async () => {
    setWorking(true);
    setError('');
    try {
      await onConfirm(record);
    } catch (err) {
      console.error('Failed to delete user:', err);
      setError(err.message || ui.deleteError);
      setWorking(false);
    }
  };

  return (
    <div className="qra-backdrop" role="presentation" onClick={onCancel}>
      <div
        className="qra-dialog"
        role="alertdialog"
        aria-modal="true"
        dir={isRTL ? 'rtl' : 'ltr'}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="qra-dialog-title">{ui.deleteTitle(record.full_name)}</h2>
        <p className="qra-dialog-body">{ui.deleteBody}</p>

        {error && <div className="qrd-alert" role="alert">{error}</div>}

        <div className="qra-dialog-actions">
          <button type="button" className="qrd-btn is-ghost" onClick={onCancel}>
            {ui.cancel}
          </button>
          <button
            type="button"
            className="qrd-danger-btn is-solid"
            disabled={working}
            onClick={confirm}
          >
            {ui.deleteConfirm}
          </button>
        </div>
      </div>
    </div>
  );
};

export default UsersAccessScreen;
