import React, { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, ChevronRight, LoaderCircle, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { requestJson } from './api';
import { OptionSelect } from './ExpertRuleEditor';
import type { ConceptGroup } from './types';

export const UNGROUPED_LABEL = 'Chưa phân nhóm';
const UNGROUPED_VALUE = 'none';

/** What the group workspace is about: `thuật ngữ` gathers terms of one meaning, `rule` gathers similar rules. */
export type GroupNoun = 'thuật ngữ' | 'rule';

/** The group being written: `new` for a group not yet saved, or the group being renamed or described. */
export type GroupEditing = ConceptGroup | 'new' | null;

export type GroupValues = { name: string; description: string | null };

type GroupDialogProps = {
  noun: GroupNoun;
  editing: GroupEditing;
  busy: boolean;
  error: string;
  onSave: (values: GroupValues) => void;
  onClose: () => void;
};

/** Creates a group, or renames and describes one; its members stay where they are and need no new review. */
export function GroupDialog({ noun, editing, busy, error, onSave, onClose }: GroupDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  useEffect(() => {
    setName(editing && editing !== 'new' ? editing.name : '');
    setDescription(editing && editing !== 'new' ? editing.description ?? '' : '');
  }, [editing]);
  if (editing === null) return null;
  const existing = editing === 'new' ? null : editing;

  return (
    <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{existing ? `Sửa nhóm: ${existing.name}` : `Nhóm ${noun} mới`}</DialogTitle>
          <DialogDescription>
            {noun === 'rule'
              ? 'Gom các rule tương đồng vào một nhóm. Chuyển rule giữa các nhóm không cần duyệt lại.'
              : 'Gom các thuật ngữ cùng ý nghĩa vào một nhóm. Chuyển thuật ngữ giữa các nhóm không cần duyệt lại.'}
          </DialogDescription>
        </DialogHeader>
        <label className="sl-metric-decision-field">
          Tên nhóm
          <Input value={name} maxLength={255} disabled={busy} onChange={event => setName(event.target.value)} />
        </label>
        <label className="sl-metric-decision-field">
          Mô tả (không bắt buộc)
          <Textarea
            value={description}
            maxLength={2000}
            disabled={busy}
            className="min-h-20"
            onChange={event => setDescription(event.target.value)}
          />
        </label>
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>Huỷ</Button>
          <Button
            disabled={busy || !name.trim()}
            onClick={() => onSave({ name: name.trim(), description: description.trim() || null })}
          >
            {busy ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
            {existing ? 'Lưu' : 'Tạo nhóm'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type GroupDeleteDialogProps = {
  noun: GroupNoun;
  group: ConceptGroup | null;
  memberCount: number;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
};

/** Confirms deleting a group; its members become ungrouped and keep their approval. */
export function GroupDeleteDialog({ noun, group, memberCount, busy, onConfirm, onClose }: GroupDeleteDialogProps) {
  if (group === null) return null;
  return (
    <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Xoá nhóm: {group.name}</DialogTitle>
          <DialogDescription>
            {memberCount === 0
              ? `Nhóm chưa có ${noun} nào.`
              : `${memberCount} ${noun} trong nhóm sẽ chuyển sang "${UNGROUPED_LABEL}"; trạng thái duyệt giữ nguyên.`}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>Huỷ</Button>
          <Button variant="destructive" disabled={busy} onClick={onConfirm}>
            {busy ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
            Xoá nhóm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Where a page's groups are created, renamed and deleted. */
export type GroupEndpoints = { groups: string; group: (groupId: number) => string };

/**
 * The state behind the group dialogs: which group is being written or deleted, and the requests that save it.
 * `reload` runs after every change; a failed delete is reported through `onError` because its dialog has closed.
 */
export function useGroupWorkspace(
  endpoints: GroupEndpoints, reload: () => Promise<void>, onError: (message: string) => void,
) {
  const [editing, setEditing] = useState<GroupEditing>(null);
  const [deleting, setDeleting] = useState<ConceptGroup | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState('');

  const startEditing = (group: GroupEditing) => { setDialogError(''); setEditing(group); };
  const save = async (values: GroupValues) => {
    if (editing === null) return;
    setBusy(true);
    setDialogError('');
    try {
      if (editing === 'new') await requestJson(endpoints.groups, 'POST', values);
      else await requestJson(endpoints.group(editing.id), 'PUT', values);
      setEditing(null);
      await reload();
    } catch (failure) {
      setDialogError(failure instanceof Error ? failure.message : 'Không lưu được nhóm.');
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (deleting === null) return;
    setBusy(true);
    try {
      await requestJson(endpoints.group(deleting.id), 'DELETE');
      await reload();
    } catch (failure) {
      onError(failure instanceof Error ? failure.message : 'Không xoá được nhóm.');
    } finally {
      setDeleting(null);
      setBusy(false);
    }
  };
  return { editing, startEditing, deleting, setDeleting, busy, dialogError, save, remove };
}

/** The groups a member can be put in, with "ungrouped" first. */
export function groupItems(groups: ConceptGroup[]) {
  return [
    { value: UNGROUPED_VALUE, label: UNGROUPED_LABEL },
    ...groups.map(group => ({ value: String(group.id), label: group.name })),
  ];
}

/**
 * A select that moves a member between groups; null stands for "ungrouped". `inline` reads as plain text among the
 * detail panel's facts and shows its frame only on hover, instead of looking like a form field.
 */
export function GroupSelect({ groups, groupId, disabled, inline, className, onChange }: {
  groups: ConceptGroup[];
  groupId: number | null;
  disabled?: boolean;
  inline?: boolean;
  className?: string;
  onChange: (groupId: number | null) => void;
}) {
  return (
    <OptionSelect
      label="Nhóm"
      items={groupItems(groups)}
      value={groupId === null ? UNGROUPED_VALUE : String(groupId)}
      className={inline ? 'sl-group-inline-select' : className}
      disabled={disabled}
      onChange={value => onChange(value === UNGROUPED_VALUE ? null : Number(value))}
    />
  );
}

type GroupedListProps<Item> = {
  noun: GroupNoun;
  groups: ConceptGroup[];
  items: Item[];
  groupIdOf: (item: Item) => number | null;
  /** While a search or filter narrows the list, groups with no matching member are hidden. */
  filtered: boolean;
  renderItem: (item: Item) => ReactNode;
  /** Left out for a read-only viewer, which hides the edit and delete buttons of every group. */
  onEditGroup?: (group: ConceptGroup) => void;
  onDeleteGroup?: (group: ConceptGroup) => void;
};

/** The members under their groups, each group collapsible, and the ungrouped members last. */
export function GroupedList<Item>(
  { noun, groups, items, groupIdOf, filtered, renderItem, onEditGroup, onDeleteGroup }: GroupedListProps<Item>,
) {
  const [collapsedKeys, setCollapsedKeys] = useState<Set<string>>(new Set());
  const toggle = (key: string) => setCollapsedKeys(current => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const knownGroupIds = new Set(groups.map(group => group.id));
  const membersOf = (groupId: number | null) => items.filter(item => {
    const itemGroupId = groupIdOf(item);
    return groupId === null ? itemGroupId === null || !knownGroupIds.has(itemGroupId) : itemGroupId === groupId;
  });
  const sections = [
    ...groups.map(group => ({ key: String(group.id), group, members: membersOf(group.id) })),
    { key: UNGROUPED_VALUE, group: null, members: membersOf(null) },
  ].filter(section => section.members.length > 0 || (!filtered && section.group !== null));

  return (
    <>
      {sections.map(({ key, group, members }) => {
        const open = !collapsedKeys.has(key);
        const name = group?.name ?? UNGROUPED_LABEL;
        return (
          <div key={key} className="sl-metrics-group">
            <div className="sl-group-heading">
              <button
                type="button"
                className="sl-metrics-disclosure sl-group-toggle"
                aria-expanded={open}
                title={group?.description ?? name}
                onClick={() => toggle(key)}
              >
                <ChevronRight /> <span>{name}</span> <span className="sl-group-count">{members.length}</span>
              </button>
              {group && onEditGroup && onDeleteGroup ? (
                <span className="sl-group-actions">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Sửa nhóm ${name}`}
                    onClick={() => onEditGroup(group)}
                  >
                    <Pencil />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Xoá nhóm ${name}`}
                    onClick={() => onDeleteGroup(group)}
                  >
                    <Trash2 />
                  </Button>
                </span>
              ) : null}
            </div>
            {!open ? null : members.length === 0 ? (
              <p className="sl-metric-muted sl-group-empty">Chưa có {noun} nào trong nhóm.</p>
            ) : members.map(renderItem)}
          </div>
        );
      })}
    </>
  );
}
