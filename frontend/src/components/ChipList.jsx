export default function ChipList({ items, getKey, getLabel, renderLabel, onRemove }) {
  if (items.length === 0) return null;
  return (
    <ul className="chips">
      {items.map((item) => {
        const labelText = getLabel ? getLabel(item) : "";
        const isCustom = typeof renderLabel === "function";
        return (
          <li key={getKey(item)} className={isCustom ? "chip chip-movie" : "chip"}>
            {isCustom ? renderLabel(item) : <span>{labelText}</span>}
            <button
              type="button"
              aria-label={`Remove ${labelText || "item"}`}
              onClick={() => onRemove(item)}
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}
