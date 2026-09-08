import { useEffect, useMemo, useRef, useState } from "react";
import {
  putCapacitySchedule,
  validateCapacitySchedule,
  applyCapacitySchedule,
  createCapacityOverride,
  deleteCapacityOverride,
} from "./api.js";

const DAYS = [
  ["mon", "Monday"],
  ["tue", "Tuesday"],
  ["wed", "Wednesday"],
  ["thu", "Thursday"],
  ["fri", "Friday"],
  ["sat", "Saturday"],
  ["sun", "Sunday"],
];
const SERVICES = [
  ["web", "Web app"],
  ["discovery", "Discovery"],
  ["assess", "Assess"],
  ["remediate", "Remediate"],
  ["gpu", "GPU vision"],
];
const ZONES = [
  ["America/Los_Angeles", "Pacific Time — Los Angeles"],
  ["America/Denver", "Mountain Time — Denver"],
  ["America/Chicago", "Central Time — Chicago"],
  ["America/New_York", "Eastern Time — New York"],
  ["Europe/London", "United Kingdom — London"],
  ["Europe/Paris", "Central Europe — Paris"],
  ["Asia/Kolkata", "India Standard Time — Kolkata"],
  ["Asia/Tokyo", "Japan Standard Time — Tokyo"],
  ["UTC", "Coordinated Universal Time"],
];
const DURATIONS = [
  ["30m", "30 minutes"],
  ["1h", "1 hour"],
  ["2h", "2 hours"],
  ["4h", "4 hours"],
  ["until_next_transition", "Until next transition"],
];
const defaults = {
  business_hours: { web: 2, discovery: 2, assess: 5, remediate: 5, gpu: 1 },
  off_hours: { web: 1, discovery: 1, assess: 1, remediate: 1, gpu: 0 },
  maximums: { web: 3, discovery: 4, assess: 10, remediate: 10, gpu: 1 },
};
const ctl = {
  minHeight: 38,
  padding: "7px 9px",
  fontSize: 13,
  border: "1px solid var(--line)",
  borderRadius: 6,
};
const lbl = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  marginBottom: 5,
};

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
function validTimezone(value) {
  try {
    new Intl.DateTimeFormat([], { timeZone: value }).format();
    return true;
  } catch {
    return false;
  }
}
function timezoneOptions(userTimezone, scheduleTimezone) {
  const supported =
    typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : [];
  return [
    ...new Set(
      [
        userTimezone,
        scheduleTimezone,
        ...ZONES.map(([zone]) => zone),
        ...supported,
      ].filter(Boolean),
    ),
  ];
}
function makeDraft(s, fallbackTimezone = "UTC") {
  return {
    enabled: !!s.enabled,
    timezone: s.timezone || fallbackTimezone,
    days: [...(s.days || [])],
    start: s.start || "06:00",
    end: s.end || "20:00",
    business_hours: { ...(s.business_hours || {}) },
    off_hours: { ...(s.off_hours || {}) },
    maximums: { ...(s.maximums || {}) },
    holidays: [...(s.holidays || [])],
  };
}
// These values are wall-clock schedule fields, not instants. Format in UTC so the browser's
// timezone cannot silently shift (for example) 06:00 to a different hour.
function time(v) {
  const [h, m] = v.split(":").map(Number);
  return new Intl.DateTimeFormat([], {
    timeZone: "UTC",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(Date.UTC(2000, 0, 1, h, m)));
}
function summary(d) {
  if (!d.enabled) return "The weekly schedule is disabled.";
  const chosen = DAYS.filter(([k]) => d.days.includes(k)).map(([, n]) => n);
  const weekdays =
    chosen.length === 5 && DAYS.slice(0, 5).every(([k]) => d.days.includes(k));
  return `${weekdays ? "Monday–Friday" : chosen.join(", ") || "No active days"}, ${time(d.start)}–${time(d.end)}${d.start > d.end ? " (overnight)" : ""} in ${d.timezone}. Off-hours capacity applies at all other times.`;
}

function WeeklyPreview({ draft }) {
  return (
    <section className="capacity-week" aria-labelledby="capacity-week-title">
      <div className="capacity-week__heading">
        <div><b id="capacity-week-title">Weekly preview</b><span>{draft.timezone}</span></div>
        <span className="capacity-week__legend"><i /> Warm window</span>
      </div>
      <div className="capacity-week__days" role="list" aria-label="Weekly warm-capacity windows">
        {DAYS.map(([key, name]) => {
          const active = draft.enabled && draft.days.includes(key)
          return <div key={key} role="listitem" className={active ? 'capacity-week__day capacity-week__day--active' : 'capacity-week__day'}>
            <b>{name.slice(0, 3)}</b>
            <span aria-hidden="true">{active ? <i /> : null}</span>
            <small>{active ? `${time(draft.start)}–${time(draft.end)}` : 'Off hours'}</small>
          </div>
        })}
      </div>
    </section>
  )
}

export default function CapacityScheduleEditor({
  snap,
  onSaved,
  onClose,
  initialView = "schedule",
}) {
  const userTimezone = useMemo(browserTimezone, []);
  const original = useMemo(
    () => makeDraft(snap, userTimezone),
    [snap, userTimezone],
  );
  const [draft, setDraft] = useState(original),
    [step, setStep] = useState(0);
  const [reason, setReason] = useState(""),
    [checked, setChecked] = useState(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(null),
    [holiday, setHoliday] = useState("");
  const [overrideReason, setOverrideReason] = useState(""),
    [overrideMode, setOverrideMode] = useState("business_hours"),
    [overrideDuration, setOverrideDuration] = useState("1h");
  const validationSequence = useRef(0);
  const dialogRef = useRef(null);
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);
  const scheduleDirty = JSON.stringify(draft) !== JSON.stringify(original);
  const dirty = scheduleDirty || !!reason;
  const timezoneChoices = useMemo(
    () => timezoneOptions(userTimezone, draft.timezone),
    [userTimezone, draft.timezone],
  );
  const errors = useMemo(() => {
    const e = {};
    if (!validTimezone(draft.timezone))
      e.timezone = "Choose a valid IANA timezone, such as America/Los_Angeles.";
    if (draft.enabled && !draft.days.length)
      e.days = "Choose at least one active day.";
    if (draft.enabled && draft.start === draft.end)
      e.hours = "Start and end times must be different.";
    SERVICES.forEach(([s]) => {
      const a = [
        draft.business_hours[s],
        draft.off_hours[s],
        draft.maximums[s],
      ];
      if (a.some((n) => !Number.isInteger(n) || n < 0))
        e[s] = "Enter whole numbers of zero or more.";
      else if (a[0] > a[2] || a[1] > a[2])
        e[s] = "Warm capacity cannot exceed the maximum.";
    });
    return e;
  }, [draft]);
  const set = (field, value) => {
    validationSequence.current += 1;
    setDraft((d) => ({ ...d, [field]: value }));
    setChecked(null);
  };
  const count = (group, service, raw) => {
    validationSequence.current += 1;
    const value = raw === "" ? "" : Number(raw);
    setDraft((d) => ({ ...d, [group]: { ...d[group], [service]: value } }));
    setChecked(null);
  };
  const validate = (showError = true) => {
    if (Object.keys(errors).length) {
      if (showError)
        setError("Fix the highlighted fields before checking the schedule.");
      return Promise.resolve();
    }
    const sequence = ++validationSequence.current;
    setBusy(true);
    setError(null);
    return validateCapacitySchedule(draft)
      .then((result) => {
        if (sequence === validationSequence.current) setChecked(result);
      })
      .catch(() => {
        if (showError && sequence === validationSequence.current)
          setError(
            "The schedule could not be checked. Your draft is still here.",
          );
      })
      .finally(() => {
        if (sequence === validationSequence.current) setBusy(false);
      });
  };
  useEffect(() => {
    if (!dirty || Object.keys(errors).length) return;
    const timer = setTimeout(() => validate(false), 600);
    return () => clearTimeout(timer);
  }, [JSON.stringify(draft)]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => {
    if (Object.keys(errors).length)
      return setError("Fix the highlighted fields before saving.");
    setBusy(true);
    setError(null);
    putCapacitySchedule({ ...draft, version: snap.version, reason })
      .then((r) => {
        if (r?.detail?.current_version !== undefined)
          return setError(
            `Someone else saved while you were editing (you had version ${r.detail.your_version}, current is ${r.detail.current_version}). Review the latest version before saving yours.`,
          );
        if (r?.detail?.findings) {
          setChecked(r.detail);
          return setError(
            "This schedule cannot be saved — review the findings below.",
          );
        }
        setReason("");
        onSaved?.(`Schedule version ${r?.version ?? snap.version + 1} saved as a draft.`);
      })
      .catch(() =>
        setError(
          "The schedule could not be saved. Nothing was changed; your draft is still here.",
        ),
      )
      .finally(() => setBusy(false));
  };
  const apply = () => {
    if (scheduleDirty)
      return setError(
        "Save these edits before applying. Apply always publishes the last saved version.",
      );
    if (!checked || checked.blocked)
      return setError(
        "Check the saved schedule successfully before applying it.",
      );
    setBusy(true);
    setError(null);
    applyCapacitySchedule({ version: snap.version, reason })
      .then(() => onSaved?.("Saved schedule sent to Azure; verification is in progress."))
      .catch((failure) => {
        const outcomes = failure?.detail?.application?.apps || [];
        const changed = outcomes
          .filter((row) => row.status === "applied")
          .map((row) => row.app);
        setError(
          changed.length
            ? `Azure applied ${changed.join(", ")}, but the fleet update was incomplete. Review application status and reconcile before retrying.`
            : "Azure did not confirm the schedule application. Review application status before retrying.",
        );
      })
      .finally(() => setBusy(false));
  };
  const close = () => {
    if (!dirty || window.confirm("Discard your unsaved schedule changes?"))
      onClose?.();
  };
  useEffect(() => {
    const escape = (event) => {
      if (event.key === "Escape" && !busy) close();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [busy, dirty]); // eslint-disable-line react-hooks/exhaustive-deps
  const override = () => {
    setBusy(true);
    createCapacityOverride({
      mode: overrideMode,
      duration: overrideDuration,
      reason: overrideReason,
      floors: overrideMode === "custom" ? draft.business_hours : null,
    })
      .then((r) => {
        if (r?.detail) setError(String(r.detail));
        else onSaved?.("Temporary override saved; Azure verification is in progress.");
      })
      .catch(() =>
        setError("The override could not be created. Nothing was changed."),
      )
      .finally(() => setBusy(false));
  };
  const endOverride = () => {
    setBusy(true);
    deleteCapacityOverride()
      .then(() => onSaved?.("Temporary override ended; the saved schedule is being restored."))
      .catch(() => setError("The override could not be ended."))
      .finally(() => setBusy(false));
  };

  if (initialView === "override")
    return (
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="false"
        tabIndex={-1}
        className="panel capacity-editor capacity-editor--override"
        aria-labelledby="override-title"
        style={{ padding: 16, display: "grid", gap: 14 }}
      >
        <header
          style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
        >
          <div>
            <h3 id="override-title" style={{ margin: 0 }}>
              Temporary override
            </h3>
            <div className="muted" style={{ fontSize: 12 }}>
              Make a time-limited capacity change without rewriting the weekly
              schedule.
            </div>
          </div>
          {onClose && (
            <button type="button" className="ghost" onClick={onClose}>
              Close
            </button>
          )}
        </header>
        {busy && <div role="status" aria-live="polite">Saving scheduling change…</div>}
        {error && <div id="override-error" role="alert">{error}</div>}
        {(!snap.application_configured || !snap.applied) && !snap.override && (
          <div role="note" className="muted">
            Temporary overrides are unavailable until this schedule is applied and Azure capacity application is enabled.
          </div>
        )}
        {snap.override ? (
          <div>
            <p>
              <b>{snap.override.mode.replace(/_/g, " ")} capacity</b>, set by{" "}
              {snap.override.actor}, expires{" "}
              {new Intl.DateTimeFormat([], {
                dateStyle: "medium",
                timeStyle: "short",
                timeZone: userTimezone,
              }).format(new Date(snap.override.expires_at))}{" "}
              ({userTimezone}, your timezone).
            </p>
            <p className="muted">
              Reason: {snap.override.reason}. Schedule version{" "}
              {snap.override.resumes_schedule_version} resumes automatically.
            </p>
            <button
              className="ghost"
              disabled={busy}
              onClick={() =>
                window.confirm(
                  "End this override and resume the saved schedule now?",
                ) && endOverride()
              }
            >
              End override
            </button>
          </div>
        ) : snap.application_configured && snap.applied ? (
          <>
            <label>
              <span style={lbl}>Capacity</span>
              <select
                id="ov-mode"
                value={overrideMode}
                style={ctl}
                onChange={(e) => setOverrideMode(e.target.value)}
              >
                <option value="business_hours">Business-hours capacity</option>
                <option value="off_hours">Off-hours capacity</option>
                <option value="custom">Custom capacity</option>
              </select>
            </label>
            {overrideMode === "custom" && (
              <fieldset
                style={{ border: "1px solid var(--line)", borderRadius: 8 }}
              >
                <legend>
                  <b>Custom warm capacity</b>
                </legend>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit,minmax(145px,1fr))",
                    gap: 8,
                  }}
                >
                  {SERVICES.filter(
                    ([service]) => draft.maximums[service] !== undefined,
                  ).map(([service, name]) => (
                    <label key={service}>
                      <span style={lbl}>{name}</span>
                      <input
                        id={`ov-${service}`}
                        type="number"
                        min="0"
                        step="1"
                        max={draft.maximums[service]}
                        value={draft.business_hours[service] ?? ""}
                        aria-invalid={!!errors[service]}
                        aria-describedby={errors[service] ? "override-capacity-error" : undefined}
                        style={{ ...ctl, width: "100%" }}
                        onChange={(e) =>
                          count("business_hours", service, e.target.value)
                        }
                      />
                    </label>
                  ))}
                </div>
                <small className="muted">
                  Each value must stay within the saved schedule maximum.
                </small>
                {Object.keys(errors).length > 0 && <small id="override-capacity-error" role="alert">Custom floors must be whole numbers within the saved maximums.</small>}
              </fieldset>
            )}
            <label>
              <span style={lbl}>Duration</span>
              <select
                id="ov-duration"
                value={overrideDuration}
                style={ctl}
                onChange={(e) => setOverrideDuration(e.target.value)}
              >
                {DURATIONS.map(([v, n]) => (
                  <option key={v} value={v}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span style={lbl}>Reason (required)</span>
              <input
                id="ov-reason"
                value={overrideReason}
                aria-required="true"
                style={{ ...ctl, width: "100%" }}
                onChange={(e) => setOverrideReason(e.target.value)}
              />
            </label>
            <div role="note" className="muted" style={{ fontSize: 12 }}>
              The override expires automatically and schedule version{" "}
              {snap.version} resumes.
            </div>
            <button
              disabled={
                busy ||
                !overrideReason.trim() ||
                (overrideMode === "custom" && Object.keys(errors).length > 0)
              }
              onClick={() =>
                window.confirm("Apply this temporary capacity override now?") &&
                override()
              }
            >
              Apply override
            </button>
          </>
        ) : null}
      </section>
    );

  return (
    <section
      ref={dialogRef}
      role="dialog"
      aria-modal="false"
      tabIndex={-1}
      className="panel capacity-editor"
      aria-labelledby="editor-title"
      style={{ padding: 16, display: "grid", gap: 16 }}
    >
      <header
        style={{ display: "flex", justifyContent: "space-between", gap: 10 }}
      >
        <div>
          <h3 id="editor-title" style={{ margin: 0 }}>
            Edit the schedule
          </h3>
          <div className="muted" style={{ fontSize: 12 }}>
            Choose when services stay warm, set capacity, then review.
          </div>
        </div>
        {onClose && (
          <button type="button" className="ghost" onClick={close}>
            Close
          </button>
        )}
      </header>
      <nav
        className="capacity-steps"
        aria-label="Schedule editing steps"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3,1fr)",
          gap: 6,
        }}
      >
        {["When", "Capacity", "Review & apply"].map((n, i) => (
          <button
            key={n}
            className={step === i ? "" : "ghost"}
            data-complete={step > i ? "true" : undefined}
            aria-current={step === i ? "step" : undefined}
            onClick={() => setStep(i)}
          >
            {i + 1}. {n}
          </button>
        ))}
      </nav>
      {error && (
        <div
          role="alert"
          style={{
            borderLeft: "4px solid var(--danger-fg, #a3222b)",
            padding: 9,
          }}
        >
          {error}
        </div>
      )}
      {busy && <div role="status" aria-live="polite">Saving or checking the schedule…</div>}
      {step === 0 && (
        <div className="capacity-editor__body" style={{ display: "grid", gap: 14 }}>
          <div>
            <h4 style={{ margin: 0 }}>When should warm capacity run?</h4>
            <p className="muted" style={{ fontSize: 12 }}>
              {summary(draft)}
            </p>
          </div>
          <WeeklyPreview draft={draft} />
          <label>
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />{" "}
            Enable this weekly schedule
          </label>
          <div>
            <label htmlFor="cap-tz">
              <span style={lbl}>Schedule timezone</span>
            </label>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                flexWrap: "wrap",
              }}
            >
              <input
                id="cap-tz"
                list="timezones"
                value={draft.timezone}
                aria-invalid={!!errors.timezone}
                aria-describedby="cap-tz-help"
                style={{ ...ctl, width: "min(100%,360px)" }}
                onChange={(e) => set("timezone", e.target.value)}
              />
              <datalist id="timezones">
                {timezoneChoices.map((zone) => (
                  <option key={zone} value={zone}>
                    {ZONES.find(([value]) => value === zone)?.[1] ||
                      zone.replaceAll("_", " ")}
                  </option>
                ))}
              </datalist>
              {draft.timezone !== userTimezone && (
                <button
                  type="button"
                  className="ghost"
                  onClick={() => set("timezone", userTimezone)}
                >
                  Use my timezone
                </button>
              )}
            </div>
            <small id="cap-tz-help" className="muted">
              Your timezone: <b>{userTimezone}</b>. Times stay at the wall-clock
              hours entered in the selected schedule timezone. Daylight-saving
              transitions follow that timezone automatically, so the UTC offset
              may change.
            </small>
            {errors.timezone && (
              <div>
                <small role="alert">{errors.timezone}</small>
              </div>
            )}
          </div>
          <fieldset style={{ border: 0, padding: 0 }}>
            <legend style={lbl}>Active days</legend>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {DAYS.map(([k, n]) => (
                <button
                  key={k}
                  className={draft.days.includes(k) ? "" : "ghost"}
                  aria-label={n}
                  aria-pressed={draft.days.includes(k)}
                  onClick={() =>
                    set(
                      "days",
                      draft.days.includes(k)
                        ? draft.days.filter((d) => d !== k)
                        : [...draft.days, k],
                    )
                  }
                >
                  {n.slice(0, 3)}
                </button>
              ))}
            </div>
            {errors.days && <small role="alert">{errors.days}</small>}
          </fieldset>
          <div style={{ display: "flex", gap: 12 }}>
            <label>
              <span style={lbl}>Starts</span>
              <input
                id="cap-start"
                type="time"
                value={draft.start}
                style={ctl}
                onChange={(e) => set("start", e.target.value)}
              />
            </label>
            <label>
              <span style={lbl}>Ends</span>
              <input
                id="cap-end"
                type="time"
                value={draft.end}
                style={ctl}
                onChange={(e) => set("end", e.target.value)}
              />
            </label>
          </div>
          {errors.hours && <small role="alert">{errors.hours}</small>}
          <div>
            <label style={lbl} htmlFor="cap-holidays">
              Holiday exception
            </label>
            <div style={{ display: "flex", gap: 7 }}>
              <input
                id="cap-holidays"
                type="date"
                value={holiday}
                style={ctl}
                onChange={(e) => setHoliday(e.target.value)}
              />
              <button
                className="ghost"
                disabled={!holiday}
                onClick={() => {
                  if (draft.holidays.includes(holiday))
                    return setError("That holiday is already included.");
                  set("holidays", [...draft.holidays, holiday].sort());
                  setHoliday("");
                }}
              >
                Add date
              </button>
            </div>
            <div aria-label="Selected holiday exceptions">
              {draft.holidays.map((d) => (
                <span className="chip" key={d}>
                  {d}{" "}
                  <button
                    aria-label={`Remove ${d}`}
                    onClick={() =>
                      set(
                        "holidays",
                        draft.holidays.filter((x) => x !== d),
                      )
                    }
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <small className="muted">
              Off-hours capacity applies for the full local holiday, then the
              weekly schedule resumes automatically.
            </small>
          </div>
        </div>
      )}
      {step === 1 && (
        <div className="capacity-editor__body">
          <h4 style={{ margin: 0 }}>Choose capacity for each service</h4>
          <p className="muted" style={{ fontSize: 12 }}>
            Warm is the normal count. Maximum is the queue-driven ceiling.
          </p>
          <div style={{ display: "grid", gap: 9 }}>
            {SERVICES.filter(([s]) => draft.maximums[s] !== undefined).map(
              ([s, n]) => (
                <fieldset
                  key={s}
                  style={{ border: "1px solid var(--line)", borderRadius: 8 }}
                >
                  <legend>
                    <b>{n}</b>
                  </legend>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit,minmax(145px,1fr))",
                      gap: 8,
                    }}
                  >
                    {[
                      ["business_hours", "Warm during business hours"],
                      ["off_hours", "Warm off hours"],
                      ["maximums", "Maximum when busy"],
                    ].map(([g, l]) => (
                      <label key={g}>
                        <span style={lbl}>{l}</span>
                        <input
                          id={`cap-${g}-${s}`}
                          type="number"
                          min="0"
                          step="1"
                          aria-invalid={!!errors[s]}
                          value={draft[g][s] ?? ""}
                          style={{ ...ctl, width: "100%" }}
                          onChange={(e) => count(g, s, e.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                  {errors[s] && <small role="alert">{errors[s]}</small>}
                  <button
                    className="ghost"
                    onClick={() =>
                      setDraft((d) => ({
                        ...d,
                        business_hours: {
                          ...d.business_hours,
                          [s]: defaults.business_hours[s],
                        },
                        off_hours: {
                          ...d.off_hours,
                          [s]: defaults.off_hours[s],
                        },
                        maximums: { ...d.maximums, [s]: defaults.maximums[s] },
                      }))
                    }
                  >
                    Use recommended defaults
                  </button>
                </fieldset>
              ),
            )}
          </div>
        </div>
      )}
      {step === 2 && (
        <div className="capacity-editor__body" style={{ display: "grid", gap: 12 }}>
          <h4 style={{ margin: 0 }}>Review &amp; apply</h4>
          <p>{summary(draft)}</p>
          <div className="panel" style={{ padding: 10 }}>
            {SERVICES.filter(([s]) => draft.maximums[s] !== undefined).map(
              ([s, n]) => (
                <div key={s}>
                  {n}: {draft.business_hours[s]} warm · {draft.off_hours[s]} off
                  hours · {draft.maximums[s]} maximum
                </div>
              ),
            )}
          </div>
          {draft.holidays.length > 0 && (
            <div role="note">
              <b>Holiday coverage:</b> off-hours capacity applies automatically on{" "}
              {draft.holidays.length} selected{" "}
              {draft.holidays.length === 1 ? "date" : "dates"} in {draft.timezone}.
            </div>
          )}
          {checked && (
            <div role="status">
              <b>
                {checked.blocked
                  ? "This schedule cannot be applied"
                  : "This schedule fits the fleet"}
              </b>
              <ul>
                {(checked.findings || []).map((f, i) => (
                  <li key={i}>{f.detail}</li>
                ))}
              </ul>
            </div>
          )}
          <label>
            <span style={lbl}>
              Reason for this change (recorded in the audit log)
            </span>
            <input
              id="cap-reason"
              value={reason}
              style={{ ...ctl, width: "100%" }}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              className="ghost"
              disabled={busy}
              onClick={() => validate()}
            >
              Check schedule
            </button>
            <button
              disabled={
                busy || !reason.trim() || Object.keys(errors).length > 0
              }
              onClick={save}
            >
              Save draft
            </button>
            {!snap.applied && snap.application_configured && (
              <button
                disabled={
                  busy ||
                  !reason.trim() ||
                  scheduleDirty ||
                  !checked ||
                  checked.blocked
                }
                onClick={apply}
              >
                Apply saved schedule
              </button>
            )}
          </div>
          {!snap.applied && snap.application_configured && scheduleDirty && (
            <div role="note" className="muted" style={{ fontSize: 12 }}>
              Save your edits first. Apply publishes the last saved version,
              never an unsaved draft.
            </div>
          )}
          {!snap.applied &&
            snap.application_configured &&
            !scheduleDirty &&
            !checked && (
              <div role="note" className="muted" style={{ fontSize: 12 }}>
                Check the saved schedule before applying it to Azure.
              </div>
            )}
          {!snap.applied && !snap.application_configured && (
            <div role="note" className="muted" style={{ fontSize: 12 }}>
              <b>Azure application is not configured in this environment.</b>{" "}
              You can save and validate the schedule, but the current Azure
              policy will remain in place.
            </div>
          )}
          <small className="muted">
            {reason.trim()
              ? "Save draft records intent; applying the saved version is a separate action."
              : "A reason is required before saving or applying."}
          </small>
        </div>
      )}
      <footer
        className="capacity-editor__footer"
        style={{
          display: "flex",
          justifyContent: "space-between",
          borderTop: "1px solid var(--line)",
          paddingTop: 12,
        }}
      >
        <button
          className="ghost"
          disabled={!step}
          onClick={() => setStep(step - 1)}
        >
          Back
        </button>
        {step < 2 && (
          <button onClick={() => setStep(step + 1)}>Continue</button>
        )}
      </footer>
    </section>
  );
}
