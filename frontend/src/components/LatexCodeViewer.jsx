import React, { useMemo } from 'react';

/**
 * Highlights a single line of LaTeX code with token coloring:
 * - Green for comments (% ...)
 * - Light Blue for control sequences / macros (\documentclass, \textbf, etc.)
 * - Yellow for braces and brackets ({, }, [, ])
 * - Pink for math symbols ($)
 * - Muted white for standard text
 */
function highlightLatexLine(line) {
  if (!line) return <span>&nbsp;</span>;

  // If the line starts with or contains a comment
  const commentIndex = line.indexOf('%');
  if (commentIndex === 0) {
    return <span style={{ color: '#6EE7B7', fontStyle: 'italic' }}>{line}</span>;
  }

  const parts = [];
  let currentPos = 0;
  const len = commentIndex !== -1 ? commentIndex : line.length;

  // Regex to match macros (\command), braces/brackets, or math mode
  const tokenRegex = /(\\[a-zA-Z@]+|[{}\[\]]|\$)/g;
  let match;

  while ((match = tokenRegex.exec(line.slice(0, len))) !== null) {
    if (match.index > currentPos) {
      parts.push(
        <span key={currentPos} style={{ color: '#E2E8F0' }}>
          {line.slice(currentPos, match.index)}
        </span>
      );
    }

    const token = match[0];
    if (token.startsWith('\\')) {
      // Macro / command
      parts.push(
        <span key={match.index} style={{ color: '#38BDF8', fontWeight: 600 }}>
          {token}
        </span>
      );
    } else if (token === '{' || token === '}' || token === '[' || token === ']') {
      // Grouping
      parts.push(
        <span key={match.index} style={{ color: '#FCD34D' }}>
          {token}
        </span>
      );
    } else if (token === '$') {
      // Math mode delimiter
      parts.push(
        <span key={match.index} style={{ color: '#F472B6', fontWeight: 700 }}>
          {token}
        </span>
      );
    }

    currentPos = match.index + token.length;
  }

  if (currentPos < len) {
    parts.push(
      <span key={currentPos} style={{ color: '#E2E8F0' }}>
        {line.slice(currentPos, len)}
      </span>
    );
  }

  // Trailing comment
  if (commentIndex !== -1) {
    parts.push(
      <span key="comment" style={{ color: '#6EE7B7', fontStyle: 'italic' }}>
        {line.slice(commentIndex)}
      </span>
    );
  }

  return parts.length > 0 ? parts : <span>&nbsp;</span>;
}

export default function LatexCodeViewer({ code, onCopy }) {
  const lines = useMemo(() => {
    return (code || '').split('\n');
  }, [code]);

  return (
    <div
      className="latex-editor-container"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#090D16',
        borderRadius: '10px',
        border: '1px solid #1E293B',
        overflow: 'hidden',
        fontFamily: 'var(--font-mono)'
      }}
    >
      {/* Editor Header Bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 14px',
          background: '#0D1424',
          borderBottom: '1px solid #1E293B',
          fontSize: '0.74rem',
          color: '#94A3B8'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#38BDF8' }} />
          <span style={{ fontWeight: 600, color: '#F1F5F9' }}>resume.tex</span>
          <span style={{ color: '#64748B' }}>•</span>
          <span>XeLaTeX 1-Page Document</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '0.7rem', color: '#64748B' }}>{lines.length} lines</span>
          <button
            className="btn btn-secondary"
            style={{ padding: '3px 10px', fontSize: '0.72rem', height: '24px', gap: '4px' }}
            onClick={onCopy}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            Copy
          </button>
        </div>
      </div>

      {/* Editor Code Body with Gutter */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          display: 'flex',
          padding: '12px 0',
          lineHeight: '1.6',
          fontSize: '0.78rem'
        }}
      >
        {/* Line Numbers Gutter */}
        <div
          style={{
            userSelect: 'none',
            padding: '0 12px 0 16px',
            textAlign: 'right',
            color: '#475569',
            borderRight: '1px solid #1E293B',
            minWidth: '46px',
            fontFamily: 'var(--font-mono)'
          }}
        >
          {lines.map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>

        {/* Highlighted Code Lines */}
        <div
          style={{
            flex: 1,
            padding: '0 16px',
            whiteSpace: 'pre',
            overflowX: 'auto',
            fontFamily: 'var(--font-mono)'
          }}
        >
          {lines.map((line, idx) => (
            <div key={idx} style={{ minHeight: '1.6em' }}>
              {highlightLatexLine(line)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
