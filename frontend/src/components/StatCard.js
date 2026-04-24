function StatCard({ label, value, detail }) {
  return (
    <article className="stat-card">
      <span className="eyebrow">{label}</span>
      <strong>{value}</strong>
      {detail ? <p>{detail}</p> : null}
    </article>
  );
}

export default StatCard;
