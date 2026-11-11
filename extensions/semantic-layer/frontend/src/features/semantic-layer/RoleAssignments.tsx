import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { requestJson, semanticLayerApi } from './api';

type SemanticLayerRole = { name: string; description: string };

type UserRoleAssignment = {
  id: number;
  username: string;
  name: string;
  is_admin: boolean;
  roles: string[];
  other_roles: string[];
};

type RoleAssignmentList = { roles: SemanticLayerRole[]; users: UserRoleAssignment[] };

/** Lets an administrator give each user the Semantic Layer's Superset roles; each tick is saved at once. */
export function RoleAssignments() {
  const [assignments, setAssignments] = useState<RoleAssignmentList>({ roles: [], users: [] });
  const [loading, setLoading] = useState(true);
  const [savingUserId, setSavingUserId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setAssignments(await requestJson<RoleAssignmentList>(semanticLayerApi.roleAssignments, 'GET'));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được danh sách người dùng.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggleRole = async (user: UserRoleAssignment, roleName: string, granted: boolean) => {
    const roles = granted ? [...user.roles, roleName] : user.roles.filter(name => name !== roleName);
    setSavingUserId(user.id);
    setError('');
    try {
      const payload = await requestJson<{ user: UserRoleAssignment }>(
        semanticLayerApi.roleAssignment(user.id), 'PUT', { roles },
      );
      setAssignments(current => ({
        ...current,
        users: current.users.map(item => (item.id === user.id ? payload.user : item)),
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không lưu được nhóm quyền.');
    } finally {
      setSavingUserId(null);
    }
  };

  return (
    <div className="sl-question-review-page">
      <p className="sl-definition-review-note">
        Nhóm quyền chỉ mở chức năng của Semantic Layer; người dùng vẫn chỉ thấy và truy vấn các dataset Superset cho
        phép (quyền datasource, row level security). Quản trị viên (Admin) luôn có đủ quyền và là người duy nhất sửa,
        duyệt nội dung.
      </p>
      {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
      {loading ? (
        <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải người dùng…</p>
      ) : (
        <table className="sl-time-semantics-table">
          <thead>
            <tr>
              <th>Người dùng</th>
              <th>Nhóm quyền khác</th>
              {assignments.roles.map(role => (
                <th key={role.name}>{role.name}<br /><span className="sl-metric-muted">{role.description}</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {assignments.users.map(user => (
              <tr key={user.id}>
                <td>{user.name} <span className="sl-metric-muted">({user.username})</span></td>
                <td className="sl-metric-muted">{user.other_roles.join(', ') || '—'}</td>
                {assignments.roles.map(role => (
                  <td key={role.name}>
                    {user.is_admin ? (
                      <span className="sl-metric-muted">Admin: đủ quyền</span>
                    ) : (
                      <Checkbox
                        aria-label={`${role.name} cho ${user.name}`}
                        checked={user.roles.includes(role.name)}
                        disabled={savingUserId !== null}
                        onCheckedChange={checked => void toggleRole(user, role.name, checked === true)}
                      />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
