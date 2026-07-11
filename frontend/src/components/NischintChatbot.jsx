import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, X, Send, ArrowRight, User, Loader2, AlertTriangle, CheckCircle, Info, Shield } from 'lucide-react';

const API = '';

const QUICK_ACTIONS = [
  { label: 'About Nischint', message: 'What is Nischint and how does it work?' },
  { label: 'School Safety', message: 'How can Nischint protect schools and students?' },
  { label: 'Corporate Safety', message: 'How does Nischint work for corporate safety?' },
  { label: 'Pilot Deployment', message: 'I want to request a pilot deployment' },
  { label: 'Investor Information', message: 'Tell me about the investment opportunity' },
  { label: 'Run Live Safety Demo', message: 'Run live safety demo' },
  { label: 'Contact Support', message: 'How can I contact the Nischint team?' },
];

const DEMO_TYPE_STYLES = {
  system: { icon: Info, color: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/20' },
  warning: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  alert: { icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/20' },
  success: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' },
  info: { icon: Info, color: 'text-teal-400', bg: 'bg-teal-500/10', border: 'border-teal-500/20' },
};

function generateSessionId() {
  return 'chat_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

export default function NischintChatbot() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId] = useState(generateSessionId);
  const [showQuickActions, setShowQuickActions] = useState(true);
  const [demoRunning, setDemoRunning] = useState(false);
  const [leadCapture, setLeadCapture] = useState(false);
  const [leadForm, setLeadForm] = useState({ name: '', institution: '', email: '', city: '' });
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, demoRunning]);

  useEffect(() => {
    if (open && messages.length === 0) {
      setMessages([{
        role: 'assistant',
        content: "Hello! I'm Nischint AI.\n\nI can help you understand how the safety platform works and guide you through pilot deployment.\n\nWhat would you like to explore?",
        type: 'text',
      }]);
    }
  }, [open]);

  const addMessage = (msg) => setMessages(prev => [...prev, msg]);

  const sendMessage = async (text) => {
    if (!text.trim() || loading || demoRunning) return;
    const userMsg = text.trim();
    setInput('');
    setShowQuickActions(false);
    addMessage({ role: 'user', content: userMsg });
    setLoading(true);

    try {
      const res = await fetch(`${API}/api/chatbot/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: userMsg }),
      });
      const data = await res.json();

      if (data.type === 'demo') {
        runDemo(data.steps);
      } else if (data.type === 'lead_prompt') {
        addMessage({ role: 'assistant', content: data.message, type: 'lead_prompt' });
        setLeadCapture(true);
      } else {
        addMessage({ role: 'assistant', content: data.message || data.error, type: 'text' });
      }
    } catch (err) {
      addMessage({ role: 'assistant', content: 'Connection error. Please try again or email hello@nischint.app.', type: 'text' });
    }
    setLoading(false);
  };

  const runDemo = async (steps) => {
    setDemoRunning(true);
    addMessage({ role: 'assistant', content: 'Starting live safety demonstration...', type: 'demo_header' });

    for (let i = 0; i < steps.length; i++) {
      await new Promise(r => setTimeout(r, steps[i].delay * 1000));
      setMessages(prev => [...prev, {
        role: 'demo',
        content: steps[i].message,
        demoType: steps[i].type,
      }]);
    }
    setDemoRunning(false);
  };

  const submitLead = async () => {
    if (!leadForm.name || !leadForm.institution || !leadForm.email) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/chatbot/lead`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, ...leadForm }),
      });
      const data = await res.json();
      addMessage({ role: 'assistant', content: data.message, type: 'text' });
      setLeadCapture(false);
      setLeadForm({ name: '', institution: '', email: '', city: '' });
    } catch {
      addMessage({ role: 'assistant', content: 'Please email hello@nischint.app and our team will follow up.', type: 'text' });
    }
    setLoading(false);
  };

  const handleLink = (path) => {
    setOpen(false);
    navigate(path);
  };

  // Render message with link detection
  const renderContent = (content) => {
    const parts = content.split(/(\/\w[\w/-]*)/g);
    return parts.map((part, i) => {
      if (part.match(/^\/[\w/-]+$/)) {
        return (
          <button key={i} onClick={() => handleLink(part)} className="text-teal-400 hover:text-teal-300 underline underline-offset-2 font-medium">
            {part}
          </button>
        );
      }
      return <span key={i}>{part}</span>;
    });
  };

  if (!open) {
    return (
      <button
        type="button"
        aria-label="Ask Nischint AI"
        onClick={() => setOpen(true)}
        className="fixed bottom-24 right-6 z-50 flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-teal-500 to-emerald-500 text-white rounded-2xl shadow-lg shadow-teal-500/20 hover:scale-105 active:scale-95 transition-transform"
        data-testid="chatbot-fab"
      >
        <Brain className="w-5 h-5" />
        <span className="text-sm font-semibold hidden sm:inline">Ask Nischint AI</span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-24 right-6 z-50 w-[380px] max-w-[calc(100vw-3rem)] h-[540px] max-h-[calc(100vh-8rem)] flex flex-col bg-[#0c1020] border border-slate-800/60 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden" data-testid="chatbot-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[#0a0e1a] border-b border-slate-800/40">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Nischint AI</p>
            <p className="text-[9px] text-emerald-400 uppercase tracking-wider">Online</p>
          </div>
        </div>
        <button type="button" aria-label="Close chatbot" onClick={() => setOpen(false)} className="text-slate-500 hover:text-white transition-colors" data-testid="chatbot-close">
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3" data-testid="chatbot-messages">
        {messages.map((msg, i) => {
          if (msg.role === 'user') {
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] px-3 py-2 bg-teal-500/20 border border-teal-500/20 rounded-xl rounded-br-sm">
                  <p className="text-xs text-slate-200 whitespace-pre-wrap">{msg.content}</p>
                </div>
              </div>
            );
          }
          if (msg.role === 'demo') {
            const style = DEMO_TYPE_STYLES[msg.demoType] || DEMO_TYPE_STYLES.system;
            const Icon = style.icon;
            return (
              <div key={i} className={`flex items-start gap-2 p-2.5 rounded-lg ${style.bg} border ${style.border}`}>
                <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${style.color}`} />
                <p className={`text-[11px] font-medium ${style.color}`}>{msg.content}</p>
              </div>
            );
          }
          // Assistant message
          return (
            <div key={i} className="flex items-start gap-2">
              <div className="w-6 h-6 rounded-md bg-gradient-to-br from-teal-500/20 to-emerald-500/20 flex items-center justify-center shrink-0 mt-0.5">
                <Shield className="w-3 h-3 text-teal-400" />
              </div>
              <div className="max-w-[85%] px-3 py-2 bg-white/[0.03] border border-slate-800/40 rounded-xl rounded-bl-sm">
                <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">{renderContent(msg.content)}</p>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex items-start gap-2">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-teal-500/20 to-emerald-500/20 flex items-center justify-center shrink-0">
              <Shield className="w-3 h-3 text-teal-400" />
            </div>
            <div className="px-3 py-2 bg-white/[0.03] border border-slate-800/40 rounded-xl">
              <Loader2 className="w-4 h-4 text-teal-400 animate-spin" />
            </div>
          </div>
        )}

        {demoRunning && (
          <div className="flex items-center gap-2 px-3 py-2">
            <Loader2 className="w-3 h-3 text-teal-400 animate-spin" />
            <span className="text-[10px] text-teal-400">Demo in progress...</span>
          </div>
        )}
      </div>

      {/* Quick Actions */}
      {showQuickActions && !leadCapture && (
        <div className="px-4 py-2 border-t border-slate-800/30 max-h-[140px] overflow-y-auto" data-testid="chatbot-quick-actions">
          <div className="flex flex-wrap gap-1.5">
            {QUICK_ACTIONS.map((action, i) => (
              <button
                key={i}
                onClick={() => sendMessage(action.message)}
                className="px-2.5 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-[10px] text-slate-400 hover:text-teal-400 hover:border-teal-500/30 transition-colors"
                data-testid={`quick-action-${i}`}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Lead Capture Form */}
      {leadCapture && (
        <div className="px-4 py-3 border-t border-slate-800/30 space-y-2" data-testid="chatbot-lead-form">
          <p className="text-[10px] text-teal-400 font-bold uppercase tracking-wider">Share your details</p>
          <input
            value={leadForm.name}
            onChange={e => setLeadForm(f => ({ ...f, name: e.target.value }))}
            placeholder="Your name"
            className="w-full px-3 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-xs text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
            data-testid="lead-name"
          />
          <input
            value={leadForm.institution}
            onChange={e => setLeadForm(f => ({ ...f, institution: e.target.value }))}
            placeholder="Institution name"
            className="w-full px-3 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-xs text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
            data-testid="lead-institution"
          />
          <input
            value={leadForm.email}
            onChange={e => setLeadForm(f => ({ ...f, email: e.target.value }))}
            placeholder="Email address"
            type="email"
            className="w-full px-3 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-xs text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
            data-testid="lead-email"
          />
          <input
            value={leadForm.city}
            onChange={e => setLeadForm(f => ({ ...f, city: e.target.value }))}
            placeholder="City (optional)"
            className="w-full px-3 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-xs text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
            data-testid="lead-city"
          />
          <div className="flex gap-2">
            <button
              onClick={submitLead}
              disabled={!leadForm.name || !leadForm.institution || !leadForm.email}
              className="flex-1 py-1.5 bg-gradient-to-r from-teal-500 to-emerald-500 text-white text-xs font-semibold rounded-lg hover:shadow-lg hover:shadow-teal-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="lead-submit"
            >
              Submit
            </button>
            <button
              onClick={() => setLeadCapture(false)}
              className="px-3 py-1.5 bg-white/[0.03] border border-slate-800/40 rounded-lg text-xs text-slate-400 hover:text-white transition-colors"
              data-testid="lead-cancel"
            >
              Skip
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      {!leadCapture && (
        <div className="px-4 py-3 border-t border-slate-800/40">
          <div className="flex items-center gap-2">
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendMessage(input)}
              placeholder="Ask anything about Nischint..."
              className="flex-1 px-3 py-2 bg-white/[0.03] border border-slate-800/40 rounded-xl text-xs text-white placeholder-slate-600 focus:border-teal-500/40 focus:outline-none"
              disabled={loading || demoRunning}
              data-testid="chatbot-input"
            />
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading || demoRunning}
              className="w-8 h-8 flex items-center justify-center bg-teal-500 rounded-lg text-white hover:bg-teal-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="chatbot-send"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
