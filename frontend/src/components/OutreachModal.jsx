import React, { useState } from 'react';
import { createPortal } from 'react-dom';

const OutreachModal = ({
  isOpen,
  onClose,
  recruiterInfo,
  messageData,
  jobTitle,
  company,
  onSendEmail,
  onCopyToClipboard,
  anchorTop = 0,
}) => {
  const [activeTab, setActiveTab] = useState('email');
  const [editingSection, setEditingSection] = useState(null);
  const [editedValues, setEditedValues] = useState({});
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  // Use messageData directly, with editedValues as overrides
  const displayData = {
    why_applying: editedValues.why_applying !== undefined ? editedValues.why_applying : (messageData?.why_applying || ''),
    why_fit: editedValues.why_fit !== undefined ? editedValues.why_fit : (messageData?.why_fit || ''),
    questions: editedValues.questions !== undefined ? editedValues.questions : (messageData?.questions || []),
    email_subject: editedValues.email_subject !== undefined ? editedValues.email_subject : (messageData?.email_subject || ''),
    email_body: editedValues.email_body !== undefined ? editedValues.email_body : (messageData?.email_body || ''),
    linkedin_message: editedValues.linkedin_message !== undefined ? editedValues.linkedin_message : (messageData?.linkedin_message || '')
  };

  const handleEditSection = (section) => {
    setEditingSection(section);
  };

  const handleSaveEdit = (section, value) => {
    setEditedValues(prev => ({
      ...prev,
      [section]: value
    }));
    setEditingSection(null);
  };

  const handleCopyEmail = () => {
    const fullEmail = `Subject: ${displayData.email_subject}\n\n${displayData.email_body}`;
    navigator.clipboard.writeText(fullEmail);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCopyLinkedIn = () => {
    navigator.clipboard.writeText(displayData.linkedin_message);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendEmail = () => {
    // Open Gmail with pre-filled draft
    const subject = encodeURIComponent(displayData.email_subject);
    const body = encodeURIComponent(displayData.email_body);
    const to = encodeURIComponent(recruiterInfo?.recruiter_email || '');

    // Gmail compose URL: https://mail.google.com/mail/?view=cm&fs=1&to=...&su=...&body=...
    const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${to}&su=${subject}&body=${body}`;

    // Open in new tab
    window.open(gmailUrl, '_blank');

    console.log('[OutreachModal] Opened Gmail draft with:', {
      to: recruiterInfo?.recruiter_email,
      subject: displayData.email_subject,
      bodyLength: displayData.email_body.length
    });
  };

  const handleMailtoFallback = () => {
    // Fallback: Open standard system mail client (Outlook, Apple Mail, etc.)
    const subject = encodeURIComponent(displayData.email_subject);
    const body = encodeURIComponent(displayData.email_body);
    const to = encodeURIComponent(recruiterInfo?.recruiter_email || '');

    window.location.href = `mailto:${to}?subject=${subject}&body=${body}`;
  };

  return createPortal(
    <div
      className="modal-overlay"
      onClick={onClose}
      style={{ alignItems: 'flex-start', paddingTop: Math.max(20, anchorTop) }}
    >
      <div className="modal-content outreach-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div>
            <h2>Personalized Outreach</h2>
            <p className="modal-subtitle">
              {jobTitle} at {company}
              {recruiterInfo?.recruiter_name && ` • ${recruiterInfo.recruiter_name}`}
            </p>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        {/* Recruiter Info */}
        {recruiterInfo?.recruiter_name ? (
          <div className="recruiter-info-box">
            <div className="recruiter-name">{recruiterInfo.recruiter_name}</div>
            {recruiterInfo?.recruiter_profile_url && (
              <a href={recruiterInfo.recruiter_profile_url} target="_blank" rel="noopener noreferrer" className="recruiter-link">
                View Profile
              </a>
            )}
          </div>
        ) : (
          <div className="recruiter-info-box" style={{ opacity: 0.7 }}>
            <div className="recruiter-name" style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
              ℹ️ Recruiter info not available for this posting
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              The message will be addressed to the Hiring Team
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="outreach-tabs">
          <button
            className={`tab-button ${activeTab === 'email' ? 'active' : ''}`}
            onClick={() => setActiveTab('email')}
          >
            Email
          </button>
          <button
            className={`tab-button ${activeTab === 'linkedin' ? 'active' : ''}`}
            onClick={() => setActiveTab('linkedin')}
          >
            LinkedIn Message
          </button>
        </div>

        {/* Tab Content */}
        <div className="outreach-content">
          {activeTab === 'email' && (
            <div className="email-section">
              {/* Subject */}
              <div className="message-section">
                <div className="section-header">
                  <span className="section-title">Subject Line</span>
                  <button
                    className="edit-button"
                    onClick={() => handleEditSection('email_subject')}
                  >
                    ✎ Edit
                  </button>
                </div>
                {editingSection === 'email_subject' ? (
                  <div className="edit-form">
                    <input
                      type="text"
                      value={displayData.email_subject}
                      onChange={(e) => setEditedValues(prev => ({
                        ...prev,
                        email_subject: e.target.value
                      }))}
                      className="edit-input"
                    />
                    <div className="edit-buttons">
                      <button
                        className="btn btn-small"
                        onClick={() => handleSaveEdit('email_subject', displayData.email_subject)}
                      >
                        Save
                      </button>
                      <button
                        className="btn btn-small btn-secondary"
                        onClick={() => setEditingSection(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="message-text">{displayData.email_subject}</div>
                )}
              </div>

              {/* Body */}
              <div className="message-section">
                <div className="section-header">
                  <span className="section-title">Email Body</span>
                  <button
                    className="edit-button"
                    onClick={() => handleEditSection('email_body')}
                  >
                    ✎ Edit
                  </button>
                </div>
                {editingSection === 'email_body' ? (
                  <div className="edit-form">
                    <textarea
                      value={displayData.email_body}
                      onChange={(e) => setEditedValues(prev => ({
                        ...prev,
                        email_body: e.target.value
                      }))}
                      className="edit-textarea"
                      rows="10"
                    />
                    <div className="edit-buttons">
                      <button
                        className="btn btn-small"
                        onClick={() => handleSaveEdit('email_body', displayData.email_body)}
                      >
                        Save
                      </button>
                      <button
                        className="btn btn-small btn-secondary"
                        onClick={() => setEditingSection(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="message-text" style={{ whiteSpace: 'pre-wrap' }}>
                    {displayData.email_body}
                  </div>
                )}
              </div>

              {/* Action Buttons */}
              <div className="action-buttons" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button className="btn" onClick={handleCopyEmail} style={{ flex: '1 1 auto' }}>
                  {copied ? '✓ Copied!' : '📋 Copy Email'}
                </button>
                <button className="btn btn-secondary" onClick={handleSendEmail} style={{ flex: '1 1 auto' }} title="Opens Gmail with pre-filled draft">
                  📧 Open in Gmail
                </button>
                <button className="btn btn-secondary" onClick={handleMailtoFallback} style={{ flex: '1 1 auto' }} title="Opens your default mail client (Outlook, Apple Mail, etc.)">
                  ✉️ Open Default Mail Client
                </button>
              </div>
            </div>
          )}

          {activeTab === 'linkedin' && (
            <div className="linkedin-section">
              <div className="message-section">
                <div className="section-header">
                  <span className="section-title">LinkedIn Message</span>
                  <button
                    className="edit-button"
                    onClick={() => handleEditSection('linkedin_message')}
                  >
                    ✎ Edit
                  </button>
                </div>
                {editingSection === 'linkedin_message' ? (
                  <div className="edit-form">
                    <textarea
                      value={displayData.linkedin_message}
                      onChange={(e) => setEditedValues(prev => ({
                        ...prev,
                        linkedin_message: e.target.value
                      }))}
                      className="edit-textarea"
                      rows="6"
                    />
                    <div className="edit-buttons">
                      <button
                        className="btn btn-small"
                        onClick={() => handleSaveEdit('linkedin_message', displayData.linkedin_message)}
                      >
                        Save
                      </button>
                      <button
                        className="btn btn-small btn-secondary"
                        onClick={() => setEditingSection(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="message-text" style={{ whiteSpace: 'pre-wrap' }}>
                    {displayData.linkedin_message}
                  </div>
                )}
              </div>

              <div className="action-buttons">
                <button className="btn" onClick={handleCopyLinkedIn}>
                  {copied ? '✓ Copied!' : '📋 Copy Message'}
                </button>
                {recruiterInfo?.recruiter_profile_url && (
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      handleCopyLinkedIn();
                      window.open(recruiterInfo.recruiter_profile_url, '_blank');
                    }}
                    title="Copies outreach note and opens LinkedIn Profile in a new tab"
                  >
                    🚀 Open LinkedIn Profile
                  </button>
                )}
                <p className="linkedin-note" style={{ flexBasis: '100%', marginTop: '6px' }}>
                  Paste this message in LinkedIn's message request box to connect with the recruiter.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Message Sections Preview */}
        <div className="message-sections-preview">
          <div className="section-label">Message Sections</div>
          <div className="sections-grid">
            <div className="section-card">
              <h4>Why I'm Applying</h4>
              <p>{displayData.why_applying}</p>
            </div>
            <div className="section-card">
              <h4>Why I Fit</h4>
              <p>{displayData.why_fit}</p>
            </div>
            <div className="section-card">
              <h4>Questions</h4>
              <ul>
                {displayData.questions?.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.85);
          display: flex;
          align-items: flex-start;
          justify-content: center;
          z-index: 1000;
          padding: 40px 20px;
          overflow-y: auto;
          pointer-events: none; /* Let scroll/mouse pass to background */
        }

        .modal-content {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 20px;
          max-width: 800px;
          width: 100%;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.7);
          margin-bottom: 40px;
          pointer-events: auto; /* Keep modal interactive */
        }

        .outreach-modal {
          padding: 0;
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          padding: 24px;
          border-bottom: 1px solid var(--border-color);
          gap: 16px;
        }

        .modal-header h2 {
          margin: 0 0 4px 0;
          font-size: 1.3rem;
        }

        .modal-subtitle {
          font-size: 0.85rem;
          color: var(--text-muted);
          margin: 0;
        }

        .modal-close {
          background: none;
          border: none;
          color: var(--text-muted);
          font-size: 1.5rem;
          cursor: pointer;
          padding: 0;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
          transition: all 0.2s;
        }

        .modal-close:hover {
          background: rgba(255, 255, 255, 0.1);
          color: var(--text-main);
        }

        .recruiter-info-box {
          padding: 16px 24px;
          background: rgba(56, 189, 248, 0.05);
          border-left: 3px solid var(--accent-primary);
          margin: 0;
        }

        .recruiter-name {
          font-weight: 600;
          color: var(--text-main);
          margin-bottom: 8px;
        }

        .recruiter-link {
          color: var(--accent-primary);
          text-decoration: none;
          font-size: 0.9rem;
          transition: color 0.2s;
        }

        .recruiter-link:hover {
          color: #38BDF8;
          text-decoration: underline;
        }

        .outreach-tabs {
          display: flex;
          gap: 0;
          padding: 0 24px;
          border-bottom: 1px solid var(--border-color);
          margin-top: 0;
        }

        .tab-button {
          background: none;
          border: none;
          color: var(--text-muted);
          padding: 16px 20px;
          cursor: pointer;
          font-weight: 500;
          font-size: 0.9rem;
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
          margin-bottom: -1px;
        }

        .tab-button:hover {
          color: var(--text-main);
        }

        .tab-button.active {
          color: var(--accent-primary);
          border-bottom-color: var(--accent-primary);
        }

        .outreach-content {
          padding: 24px;
        }

        .message-section {
          margin-bottom: 24px;
        }

        .section-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .section-title {
          font-weight: 600;
          color: var(--text-main);
          font-size: 0.95rem;
        }

        .edit-button {
          background: none;
          border: none;
          color: var(--accent-primary);
          cursor: pointer;
          font-size: 0.85rem;
          padding: 4px 8px;
          border-radius: 6px;
          transition: all 0.2s;
        }

        .edit-button:hover {
          background: rgba(56, 189, 248, 0.1);
        }

        .message-text {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 16px;
          color: var(--text-main);
          line-height: 1.6;
          font-size: 0.9rem;
        }

        .edit-form {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .edit-input,
        .edit-textarea {
          background: var(--input-bg);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 12px;
          color: var(--text-main);
          font-family: var(--font-sans);
          font-size: 0.9rem;
        }

        .edit-input:focus,
        .edit-textarea:focus {
          outline: none;
          border-color: var(--accent-primary);
          box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15);
        }

        .edit-textarea {
          resize: vertical;
          min-height: 120px;
        }

        .edit-buttons {
          display: flex;
          gap: 10px;
        }

        .btn-small {
          padding: 8px 16px;
          font-size: 0.85rem;
        }

        .action-buttons {
          display: flex;
          gap: 12px;
          margin-top: 20px;
        }

        .action-buttons .btn {
          flex: 1;
        }

        .linkedin-note {
          font-size: 0.85rem;
          color: var(--text-muted);
          margin-top: 16px;
          padding: 12px;
          background: rgba(56, 189, 248, 0.05);
          border-radius: 8px;
          border-left: 3px solid var(--accent-primary);
        }

        .message-sections-preview {
          padding: 24px;
          border-top: 1px solid var(--border-color);
          background: rgba(255, 255, 255, 0.01);
        }

        .sections-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
          margin-top: 12px;
        }

        .section-card {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border-color);
          border-radius: 10px;
          padding: 16px;
        }

        .section-card h4 {
          margin: 0 0 8px 0;
          font-size: 0.9rem;
          color: var(--accent-primary);
          font-weight: 600;
        }

        .section-card p,
        .section-card ul {
          margin: 0;
          font-size: 0.85rem;
          color: var(--text-muted);
          line-height: 1.5;
        }

        .section-card ul {
          padding-left: 20px;
        }

        .section-card li {
          margin-bottom: 6px;
        }

        @media (max-width: 640px) {
          .modal-content {
            max-height: 95vh;
            border-radius: 16px;
          }

          .modal-header {
            flex-direction: column;
            gap: 12px;
          }

          .sections-grid {
            grid-template-columns: 1fr;
          }

          .action-buttons {
            flex-direction: column;
          }
        }
      `}</style>
    </div>,
    document.body
  );
};

export default OutreachModal;
