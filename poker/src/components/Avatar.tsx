import styles from "./Avatar.module.css";

export function Avatar({ index, size = "md", selected = false }: { index: number; size?: "sm" | "md" | "lg"; selected?: boolean }) {
  const column = index % 4;
  const row = Math.floor(index / 4);
  return (
    <span
      className={`${styles.avatar} ${styles[size]} ${selected ? styles.selected : ""}`}
      style={{ backgroundPosition: `${column * 33.333}% ${row * 50}%` }}
      role="img"
      aria-label={`Аватар ${index + 1}`}
    />
  );
}
