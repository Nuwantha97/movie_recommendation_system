import { useEffect, useId, useRef, useState } from "react";
import { useDebounce } from "../hooks";
import { isAbort } from "../api";

const MAX_VISIBLE = 45;

export default function AsyncCombobox({
  id,
  label,
  placeholder,
  minChars = 2,
  disabled = false,
  showEmptyMessage = true,
  fetchOptions,   // (query, signal) => Promise<item[]>
  onSelect,       // (item) => void
  getKey,         // (item) => string
  renderOption,   // (item) => ReactNode
  isSelected,     // (item) => boolean, selected items are hidden from suggestions
}) {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const query = text.trim();
  const debounced = useDebounce(query, 250);
  const rootRef = useRef(null);
  const listId = useId();

  const current = result?.query === query && debounced === query ? result : null;
  const currentStatus = current ? current.status : "loading";

  useEffect(() => {
    if (disabled || debounced.length < minChars) {
      return;
    }
    const controller = new AbortController();
    fetchOptions(debounced, controller.signal)
      .then((items) => {
        if (controller.signal.aborted) return;
        setResult({ query: debounced, status: "idle", items });
        setActive(0);
      })
      .catch((err) => {
        if (controller.signal.aborted || isAbort(err)) return;
        setResult({ query: debounced, status: "error", error: err.message || "Search failed.", items: [] });
      });
    return () => controller.abort();
  }, [debounced, minChars, disabled, fetchOptions]);

  useEffect(() => {
    const onDown = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const visible = (current?.items ?? []).filter((o) => !isSelected(o)).slice(0, MAX_VISIBLE);
  const showPanel = !disabled && open && query.length >= minChars &&
    (showEmptyMessage || visible.length > 0 || currentStatus === "error");

  function pick(item) {
    onSelect(item);
    setText("");
    setOpen(false);
  }

  function scrollActiveIntoView(index) {
    requestAnimationFrame(() => {
      const activeEl = document.getElementById(`${listId}-opt-${index}`);
      activeEl?.scrollIntoView({ block: "nearest" });
    });
  }

  function onKeyDown(e) {
    if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => {
        const next = visible.length ? (a + 1) % visible.length : 0;
        scrollActiveIntoView(next);
        return next;
      });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => {
        const next = visible.length ? (a - 1 + visible.length) % visible.length : 0;
        scrollActiveIntoView(next);
        return next;
      });
    } else if (e.key === "Enter") {
      if (showPanel && visible[active]) {
        e.preventDefault();
        pick(visible[active]);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const activeDescendantId =
    showPanel && visible[active] ? `${listId}-opt-${active}` : undefined;

  return (
    <div className="combo" ref={rootRef}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-label={label}
        aria-expanded={showPanel}
        aria-controls={showPanel ? listId : undefined}
        aria-autocomplete="list"
        aria-activedescendant={activeDescendantId}
        disabled={disabled}
        placeholder={disabled ? "Selection limit reached" : placeholder}
        value={disabled ? "" : text}
        autoComplete="off"
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {showPanel && (
        <ul
          className="combo-list"
          id={listId}
          role="listbox"
          aria-busy={currentStatus === "loading"}
        >
          {currentStatus === "loading" && (
            <>
              {[0, 1, 2].map((i) => (
                <li key={`combo-sk-${i}`} className="combo-skeleton" aria-hidden="true">
                  <div className="sk sk-combo-thumb" />
                  <div className="sk-combo-text">
                    <div className="sk sk-combo-title" />
                    <div className="sk sk-combo-sub" />
                  </div>
                </li>
              ))}
            </>
          )}
          {currentStatus === "error" && <li className="combo-note error">{current.error}</li>}
          {showEmptyMessage && currentStatus === "idle" && visible.length === 0 && (
            <li className="combo-note">No matches</li>
          )}
          {visible.map((item, i) => (
            <li
              id={`${listId}-opt-${i}`}
              key={getKey(item)}
              role="option"
              aria-selected={i === active}
              className={i === active ? "combo-option active" : "combo-option"}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(item)}
            >
              {renderOption(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
