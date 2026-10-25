/** One numbered section of the report: mono kicker, heading, optional meta line, body. */
export default function ReportSection({
  id, n, title, meta, children,
}: {
  id: string;
  n: number;
  title: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rc-sec" aria-labelledby={`${id}-h`}>
      <div className="rc-sec-head">
        <span className="rc-kicker" aria-hidden="true">{String(n).padStart(2, '0')}</span>
        <h2 id={`${id}-h`}>{title}</h2>
        {meta && <span className="rc-meta">{meta}</span>}
      </div>
      {children}
    </section>
  );
}
