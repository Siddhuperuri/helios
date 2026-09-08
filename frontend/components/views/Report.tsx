'use client';

import { useMemo, useState } from 'react';

import { api } from '@/lib/api';
import { useAsync } from '@/lib/useAsync';
import { Button, Callout, ErrorState, LoadingPanel, Section } from '@/components/ui';

/**
 * Report export.
 *
 * The report is generated server-side as Markdown so the same document is produced whether
 * it is read here, downloaded, or printed. Rendering happens client-side with a small,
 * deliberately limited converter — no HTML from the payload is ever injected, which keeps
 * the surface for content injection closed even though the source is our own API.
 */
export function ReportView({ analysisId }: { analysisId: string }) {
  const [copied, setCopied] = useState(false);
  const report = useAsync(() => api.report(analysisId), [analysisId]);

  const html = useMemo(() => (report.data ? renderMarkdown(report.data) : ''), [report.data]);

  function download() {
    if (!report.data) return;
    const blob = new Blob([report.data], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `helios-report-${analysisId}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function copy() {
    if (!report.data) return;
    try {
      await navigator.clipboard.writeText(report.data);
      setCopied(true);
      setTimeout(() => setCopied(false), 2200);
    } catch {
      setCopied(false);
    }
  }

  if (report.error) return <ErrorState message={report.error.message} onRetry={report.reload} />;
  if (!report.data) return <LoadingPanel message="Assembling the report…" />;

  return (
    <div className="space-y-8">
      <Section
        label="Scientific report"
        title="Exportable summary of this analysis"
        description="States measured results only. It contains no generated interpretation of whether the model is fit for a particular purpose — that judgement belongs to the reader."
        actions={
          <div className="no-print flex gap-2">
            <Button size="sm" onClick={copy}>
              {copied ? 'Copied' : 'Copy Markdown'}
            </Button>
            <Button size="sm" onClick={download}>
              Download .md
            </Button>
            <Button size="sm" onClick={() => window.print()}>
              Print
            </Button>
          </div>
        }
      >
        <Callout tone="info" title="Format">
          Generated as Markdown so it can be pasted into a thesis, a lab notebook or a pull
          request without reformatting. Every figure in it comes from this run.
        </Callout>
      </Section>

      <article
        className="report-body max-w-none border border-line bg-surface-1 p-6 sm:p-8"
        dangerouslySetInnerHTML={{ __html: html }}
      />

      <style jsx global>{`
        .report-body h1 {
          font-size: 1.5rem;
          font-weight: 500;
          letter-spacing: -0.02em;
          color: #e7e9ec;
          margin-bottom: 1rem;
        }
        .report-body h2 {
          font-size: 1rem;
          font-weight: 500;
          color: #e7e9ec;
          margin-top: 2.25rem;
          margin-bottom: 0.85rem;
          padding-bottom: 0.4rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.13);
        }
        .report-body h3 {
          font-size: 0.85rem;
          font-weight: 500;
          color: #99a0aa;
          margin-top: 1.5rem;
          margin-bottom: 0.6rem;
        }
        .report-body p {
          font-size: 0.8125rem;
          line-height: 1.65;
          color: #99a0aa;
          margin-bottom: 0.85rem;
        }
        .report-body strong {
          color: #e7e9ec;
          font-weight: 500;
        }
        .report-body code {
          font-family: var(--font-plex-mono), monospace;
          font-size: 0.75rem;
          color: #f2a93b;
        }
        .report-body table {
          width: 100%;
          border-collapse: collapse;
          margin: 0.85rem 0 1.4rem;
          font-family: var(--font-plex-mono), monospace;
          font-size: 0.72rem;
          font-variant-numeric: tabular-nums;
        }
        .report-body th {
          text-align: left;
          padding: 0.4rem 0.6rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.13);
          color: #7a828e;
          font-weight: 500;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          font-size: 0.65rem;
        }
        .report-body td {
          padding: 0.4rem 0.6rem;
          border-bottom: 1px solid rgba(255, 255, 255, 0.07);
          color: #99a0aa;
        }
        .report-body blockquote {
          border-left: 2px solid #f2a93b;
          padding: 0.55rem 0 0.55rem 0.85rem;
          margin: 0.85rem 0;
          background: rgba(255, 255, 255, 0.015);
        }
        .report-body blockquote p {
          margin: 0;
          font-size: 0.75rem;
          color: #99a0aa;
        }
        .report-body ol,
        .report-body ul {
          margin: 0.6rem 0 1.1rem 1.15rem;
          font-size: 0.8125rem;
          line-height: 1.65;
          color: #99a0aa;
        }
        .report-body ol {
          list-style: decimal;
        }
        .report-body ul {
          list-style: disc;
        }
        .report-body li {
          margin-bottom: 0.35rem;
        }
        .report-body hr {
          border: none;
          border-top: 1px solid rgba(255, 255, 255, 0.07);
          margin: 2rem 0;
        }
        .report-body em {
          color: #7a828e;
        }
        @media (max-width: 640px) {
          .report-body table {
            display: block;
            overflow-x: auto;
          }
        }
      `}</style>
    </div>
  );
}

/**
 * A minimal Markdown renderer for the report subset.
 *
 * Input is escaped before any markup is produced, so nothing in the payload can inject
 * HTML. The backend is the only source of this content, but escaping first is the correct
 * default regardless of how trusted the source is believed to be.
 */
function renderMarkdown(src: string): string {
  const escape = (s: string) =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

  const inline = (s: string) =>
    escape(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');

  const lines = src.split('\n');
  const out: string[] = [];
  let inTable = false;
  let inList: 'ol' | 'ul' | null = null;

  const closeList = () => {
    if (inList) {
      out.push(`</${inList}>`);
      inList = null;
    }
  };
  const closeTable = () => {
    if (inTable) {
      out.push('</tbody></table>');
      inTable = false;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      closeTable();
      continue;
    }

    // Table separator row — consumed as part of the header.
    if (/^\|[\s:|-]+\|$/.test(trimmed)) continue;

    if (trimmed.startsWith('|')) {
      const cells = trimmed.slice(1, -1).split('|').map((c) => c.trim());
      const next = (lines[i + 1] ?? '').trim();
      if (!inTable && /^\|[\s:|-]+\|$/.test(next)) {
        closeList();
        out.push('<table><thead><tr>');
        cells.forEach((c) => out.push(`<th>${inline(c)}</th>`));
        out.push('</tr></thead><tbody>');
        inTable = true;
      } else if (inTable) {
        out.push('<tr>');
        cells.forEach((c) => out.push(`<td>${inline(c)}</td>`));
        out.push('</tr>');
      }
      continue;
    }
    closeTable();

    if (trimmed.startsWith('### ')) {
      closeList();
      out.push(`<h3>${inline(trimmed.slice(4))}</h3>`);
    } else if (trimmed.startsWith('## ')) {
      closeList();
      out.push(`<h2>${inline(trimmed.slice(3))}</h2>`);
    } else if (trimmed.startsWith('# ')) {
      closeList();
      out.push(`<h1>${inline(trimmed.slice(2))}</h1>`);
    } else if (trimmed.startsWith('> ')) {
      closeList();
      out.push(`<blockquote><p>${inline(trimmed.slice(2))}</p></blockquote>`);
    } else if (trimmed === '---') {
      closeList();
      out.push('<hr />');
    } else if (/^\d+\.\s/.test(trimmed)) {
      if (inList !== 'ol') {
        closeList();
        out.push('<ol>');
        inList = 'ol';
      }
      out.push(`<li>${inline(trimmed.replace(/^\d+\.\s/, ''))}</li>`);
    } else if (/^[-*]\s/.test(trimmed)) {
      if (inList !== 'ul') {
        closeList();
        out.push('<ul>');
        inList = 'ul';
      }
      out.push(`<li>${inline(trimmed.slice(2))}</li>`);
    } else {
      closeList();
      out.push(`<p>${inline(trimmed)}</p>`);
    }
  }

  closeList();
  closeTable();
  return out.join('\n');
}
