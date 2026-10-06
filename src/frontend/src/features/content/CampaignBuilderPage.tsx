import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CampaignCollaboratorsPanel } from "./CampaignCollaboratorsPanel";
import { ModuleEditorsPresence } from "./ModuleEditorsPresence";
import type {
  Campaign,
  CampaignModule,
  CampaignTarget,
  ContentGroup,
  ModuleBody,
  Requirement,
} from "./types";
import { useAdminUserOptions } from "./useAdminUserOptions";
import { useEditors } from "./useModuleEditors";

const inputClassName =
  "rounded-xl border border-border bg-bg-elevated px-3.5 py-2.5 text-sm transition-colors focus:border-primary focus:outline-none";
const cardClassName =
  "flex flex-col gap-4 rounded-2xl border border-border bg-bg-elevated p-5 shadow-[var(--shadow)]";
const smallButtonClassName =
  "rounded-full border border-border px-3 py-1 text-xs font-medium disabled:opacity-40";

/** Move the item at `from` so it lands at index `to`. */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) {
    return items;
  }
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/**
 * Builds a campaign in draft. One page, one Save: details, an ordered module
 * list, and group targets. Ordering works by drag-and-drop or, equally, by the
 * move buttons — the buttons are the keyboard and screen-reader path, so
 * neither is optional.
 *
 * Individual (named-person) targets are an Administrator's act: only an
 * Administrator gets the picker and the remove control. For anyone else the
 * ones that already exist are shown read-only and sent back untouched so a
 * save here never drops them.
 */
export function CampaignBuilderPage({ isAdministrator = false }: { isAdministrator?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { campaignId } = useParams<{ campaignId: string }>();
  const isNew = campaignId === undefined;
  const editors = useEditors(campaignId ? `/api/content/campaigns/${campaignId}/editing` : undefined);
  const userOptions = useAdminUserOptions(isAdministrator);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [personToAdd, setPersonToAdd] = useState("");

  const [loaded, setLoaded] = useState(isNew);
  const [notFound, setNotFound] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [autoReminders, setAutoReminders] = useState(true);
  const [sequential, setSequential] = useState(false);
  const [modules, setModules] = useState<CampaignModule[]>([]);
  const [targets, setTargets] = useState<CampaignTarget[]>([]);

  const [availableModules, setAvailableModules] = useState<ModuleBody[]>([]);
  const [groups, setGroups] = useState<ContentGroup[]>([]);
  const [moduleToAdd, setModuleToAdd] = useState("");
  const [groupToAdd, setGroupToAdd] = useState("");
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function applyCampaign(campaign: Campaign) {
    setCampaign(campaign);
    setName(campaign.name);
    setDescription(campaign.description ?? "");
    setStartDate(campaign.start_date ?? "");
    setDueDate(campaign.due_date ?? "");
    setAutoReminders(campaign.auto_reminders);
    setSequential(campaign.sequential);
    setModules(campaign.modules);
    setTargets(campaign.targets);
  }

  useEffect(() => {
    if (!campaignId) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`/api/content/campaigns/${campaignId}`);
        if (cancelled) return;
        if (response.status === 404) {
          setNotFound(true);
          return;
        }
        if (!response.ok) {
          setError(t("campaigns.load_error"));
          return;
        }
        applyCampaign(await response.json());
        setLoaded(true);
      } catch {
        if (!cancelled) setError(t("campaigns.load_error"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [campaignId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [moduleResponse, groupResponse] = await Promise.all([
          fetch("/api/content/modules"),
          fetch("/api/content/groups"),
        ]);
        if (cancelled) return;
        if (moduleResponse.ok) setAvailableModules(await moduleResponse.json());
        if (groupResponse.ok) setGroups(await groupResponse.json());
      } catch {
        // The pickers stay empty; what is already in the campaign still renders.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // A campaign names a translation group, so list each group once.
  const pickableModules = availableModules.filter(
    (module, index, all) =>
      all.findIndex((other) => other.translation_group_id === module.translation_group_id) ===
        index && !modules.some((row) => row.translation_group_id === module.translation_group_id),
  );
  const pickableGroups = groups.filter(
    (group) => !targets.some((target) => target.type === "group" && target.id === group.id),
  );

  function addModule() {
    const chosen = availableModules.find((module) => module.translation_group_id === moduleToAdd);
    if (!chosen) return;
    setModules((current) => [
      ...current,
      {
        translation_group_id: chosen.translation_group_id,
        position: current.length,
        requirement: "mandatory",
        title: chosen.title,
        availability: chosen.status === "published" ? "published" : "unpublished",
      },
    ]);
    setModuleToAdd("");
  }

  function addGroup() {
    const chosen = groups.find((group) => group.id === groupToAdd);
    if (!chosen) return;
    setTargets((current) => [...current, { type: "group", id: chosen.id, name: chosen.name }]);
    setGroupToAdd("");
  }

  const pickablePeople = userOptions.filter(
    (person) => !targets.some((target) => target.type === "user" && target.id === person.id),
  );

  function addPerson() {
    const chosen = userOptions.find((person) => person.id === personToAdd);
    if (!chosen) return;
    setTargets((current) => [...current, { type: "user", id: chosen.id, name: chosen.label }]);
    setPersonToAdd("");
  }

  async function handleDelete() {
    if (!campaignId || !window.confirm(t("campaigns.delete_confirm"))) return;
    try {
      const response = await fetch(`/api/content/campaigns/${campaignId}`, { method: "DELETE" });
      if (!response.ok) {
        setError(t("campaigns.delete_error"));
        return;
      }
      navigate("/content/campaigns", { replace: true });
    } catch {
      setError(t("campaigns.delete_error"));
    }
  }

  function setRequirement(index: number, requirement: Requirement) {
    setModules((current) =>
      current.map((row, i) => (i === index ? { ...row, requirement } : row)),
    );
  }

  function describeFailure(response: Response): string {
    if (response.status === 403) return t("campaigns.error_forbidden");
    if (response.status === 404) return t("campaigns.error_not_found");
    return t("campaigns.error_unknown");
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    if (name.trim() === "") {
      setError(t("campaigns.error_name_required"));
      return;
    }
    if (startDate && dueDate && dueDate < startDate) {
      setError(t("campaigns.error_dates"));
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      name: name.trim(),
      description: description.trim() === "" ? null : description.trim(),
      start_date: startDate === "" ? null : startDate,
      due_date: dueDate === "" ? null : dueDate,
      auto_reminders: autoReminders,
      sequential,
      modules: modules.map((row) => ({
        translation_group_id: row.translation_group_id,
        requirement: row.requirement,
      })),
      targets: targets.map((target) => ({ type: target.type, id: target.id })),
    };
    try {
      const response = await fetch(
        isNew ? "/api/content/campaigns" : `/api/content/campaigns/${campaignId}`,
        {
          method: isNew ? "POST" : "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok) {
        setError(describeFailure(response));
        return;
      }
      const campaign: Campaign = await response.json();
      if (isNew) {
        navigate(`/content/campaigns/${campaign.id}`, { replace: true });
        return;
      }
      applyCampaign(campaign);
      setSaved(true);
    } catch {
      setError(t("campaigns.error_unknown"));
    } finally {
      setBusy(false);
    }
  }

  if (notFound) {
    return (
      <section className="flex flex-col gap-4">
        <p role="alert" className="text-sm text-danger">
          {t("campaigns.error_not_found")}
        </p>
        <Link to="/content/campaigns" className="text-sm underline">
          {t("campaigns.back")}
        </Link>
      </section>
    );
  }
  if (!loaded) {
    return error ? (
      <p role="alert" className="text-sm text-danger">
        {error}
      </p>
    ) : null;
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-6">
      <ModuleEditorsPresence editors={editors} subject="campaign" />
      <div className="flex flex-col gap-1">
        <Link to="/content/campaigns" className="text-sm text-fg-muted underline">
          {t("campaigns.back")}
        </Link>
        <h2 className="text-xl font-semibold">
          {isNew ? t("campaigns.new_heading") : t("campaigns.edit_heading")}
        </h2>
      </div>

      <section className={cardClassName}>
        <h3 className="text-lg font-medium">{t("campaigns.details_heading")}</h3>
        <label className="flex flex-col gap-1 text-sm">
          {t("campaigns.name_label")}
          <input
            value={name}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
            className={inputClassName}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("campaigns.description_label")}
          <textarea
            value={description}
            rows={3}
            onChange={(event) => setDescription(event.target.value)}
            className={inputClassName}
          />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            {t("campaigns.start_date_label")}
            <input
              type="date"
              value={startDate}
              onChange={(event) => setStartDate(event.target.value)}
              className={inputClassName}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {t("campaigns.due_date_label")}
            <input
              type="date"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
              className={inputClassName}
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoReminders}
            onChange={(event) => setAutoReminders(event.target.checked)}
          />
          {t("campaigns.auto_reminders_label")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={sequential}
            onChange={(event) => setSequential(event.target.checked)}
          />
          {t("campaigns.sequential_label")}
        </label>
      </section>

      <section className={cardClassName}>
        <div>
          <h3 className="text-lg font-medium">{t("campaigns.modules_heading")}</h3>
          <p className="text-sm text-fg-muted">{t("campaigns.modules_description")}</p>
        </div>

        {modules.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("campaigns.modules_empty")}</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {modules.map((row, index) => {
              const title = row.title ?? t("campaigns.untitled_module");
              return (
                <li
                  key={row.translation_group_id}
                  draggable
                  onDragStart={() => setDragIndex(index)}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    if (dragIndex !== null) setModules((c) => moveItem(c, dragIndex, index));
                    setDragIndex(null);
                  }}
                  onDragEnd={() => setDragIndex(null)}
                  className={`flex flex-wrap items-center gap-3 rounded-xl border border-border bg-bg p-3 text-sm ${
                    dragIndex === index ? "opacity-50" : ""
                  }`}
                >
                  <span
                    aria-label={t("campaigns.drag_handle", { title })}
                    className="cursor-grab select-none text-fg-muted"
                  >
                    ⠿
                  </span>
                  <span className="w-6 text-fg-muted">{index + 1}.</span>
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="font-medium">{title}</span>
                    {row.availability !== "published" && (
                      <span className="text-xs text-warning">
                        {t(`campaigns.availability_${row.availability}`)}
                      </span>
                    )}
                  </div>
                  <select
                    aria-label={t("campaigns.requirement_label", { title })}
                    value={row.requirement}
                    onChange={(event) => setRequirement(index, event.target.value as Requirement)}
                    className={inputClassName}
                  >
                    <option value="mandatory">{t("campaigns.requirement_mandatory")}</option>
                    <option value="recommended">{t("campaigns.requirement_recommended")}</option>
                  </select>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      disabled={index === 0}
                      aria-label={t("campaigns.move_up", { title })}
                      onClick={() => setModules((c) => moveItem(c, index, index - 1))}
                      className={smallButtonClassName}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      disabled={index === modules.length - 1}
                      aria-label={t("campaigns.move_down", { title })}
                      onClick={() => setModules((c) => moveItem(c, index, index + 1))}
                      className={smallButtonClassName}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      aria-label={t("campaigns.remove_module", { title })}
                      onClick={() => setModules((c) => c.filter((_, i) => i !== index))}
                      className={`${smallButtonClassName} border-danger text-danger`}
                    >
                      ✕
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
            {t("campaigns.add_module_label")}
            <select
              value={moduleToAdd}
              onChange={(event) => setModuleToAdd(event.target.value)}
              className={inputClassName}
            >
              <option value="">{t("campaigns.add_module_placeholder")}</option>
              {pickableModules.map((module) => (
                <option key={module.translation_group_id} value={module.translation_group_id}>
                  {module.title}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!moduleToAdd}
            onClick={addModule}
            className="rounded-full border border-border px-4 py-2.5 text-sm font-medium disabled:opacity-40"
          >
            {t("campaigns.add_module_button")}
          </button>
        </div>
      </section>

      <section className={cardClassName}>
        <div>
          <h3 className="text-lg font-medium">{t("campaigns.targets_heading")}</h3>
          <p className="text-sm text-fg-muted">{t("campaigns.targets_description")}</p>
        </div>

        {targets.length === 0 ? (
          <p className="text-sm text-fg-muted">{t("campaigns.targets_empty")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {targets.map((target) => {
              const label = target.name ?? t("campaigns.individual_target");
              const group = groups.find((g) => g.id === target.id);
              return (
                <li
                  key={`${target.type}:${target.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-bg p-3 text-sm"
                >
                  <span className="font-medium">
                    {label}
                    {target.type === "group" && group && (
                      <span className="ml-2 text-xs font-normal text-fg-muted">
                        {t("campaigns.member_count", { count: group.member_count })}
                      </span>
                    )}
                  </span>
                  {(target.type === "group" || isAdministrator) && (
                    <button
                      type="button"
                      aria-label={t("campaigns.remove_target", { name: label })}
                      onClick={() =>
                        setTargets((c) => c.filter((x) => !(x.type === target.type && x.id === target.id)))
                      }
                      className={`${smallButtonClassName} border-danger text-danger`}
                    >
                      ✕
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
            {t("campaigns.add_group_label")}
            <select
              value={groupToAdd}
              onChange={(event) => setGroupToAdd(event.target.value)}
              className={inputClassName}
            >
              <option value="">{t("campaigns.add_group_placeholder")}</option>
              {pickableGroups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name} ({t("campaigns.member_count", { count: group.member_count })})
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={!groupToAdd}
            onClick={addGroup}
            className="rounded-full border border-border px-4 py-2.5 text-sm font-medium disabled:opacity-40"
          >
            {t("campaigns.add_group_button")}
          </button>
        </div>

        {isAdministrator && (
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm">
              {t("campaigns.add_individual_label")}
              <select
                value={personToAdd}
                onChange={(event) => setPersonToAdd(event.target.value)}
                className={inputClassName}
              >
                <option value="">{t("campaigns.add_individual_placeholder")}</option>
                {pickablePeople.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!personToAdd}
              onClick={addPerson}
              className="rounded-full border border-border px-4 py-2.5 text-sm font-medium disabled:opacity-40"
            >
              {t("campaigns.add_individual_button")}
            </button>
          </div>
        )}
      </section>

      {campaign && (
        <CampaignCollaboratorsPanel
          campaign={campaign}
          isAdministrator={isAdministrator}
          onChanged={(updated) => setCampaign(updated)}
        />
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm text-fg-muted">
          {t("campaigns.saved")}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className="self-start rounded-full bg-[image:var(--gradient)] px-6 py-2.5 text-sm font-semibold text-primary-fg transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)] disabled:opacity-60 disabled:hover:translate-y-0"
      >
        {isNew ? t("campaigns.create") : t("campaigns.save")}
      </button>
      {campaign?.can_manage && campaign.status === "draft" && (
        <button
          type="button"
          onClick={() => void handleDelete()}
          className="self-start rounded-full border border-danger px-5 py-2 text-sm font-medium text-danger"
        >
          {t("campaigns.delete_draft")}
        </button>
      )}
    </form>
  );
}
