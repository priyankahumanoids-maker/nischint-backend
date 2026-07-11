import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Mic, MicOff, Plus, Trash2, Loader2, History, ChevronDown, ChevronUp,
  Phone, BellRing, ShieldAlert, CheckCircle, XCircle, Zap, Volume2,
  Settings, AlertTriangle, Clock,
} from 'lucide-react';
import api from '../api';
import { toast } from 'sonner';

const ACTION_META = {
  sos: { icon: ShieldAlert, color: '#ef4444', label: 'SOS Silent Mode', bg: 'bg-red-50', border: 'border-red-200' },
  fake_call: { icon: Phone, color: '#2563eb', label: 'Escape Call', bg: 'bg-blue-50', border: 'border-blue-200' },
  fake_notification: { icon: BellRing, color: '#7c3aed', label: 'Escape Notification', bg: 'bg-violet-50', border: 'border-violet-200' },
};

const VoiceTriggerPage = ({ onVoiceTrigger }) => {
  const [commands, setCommands] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [recognizing, setRecognizing] = useState(false);

  // New command form state
  const [newPhrase, setNewPhrase] = useState('');
  const [newAction, setNewAction] = useState('fake_call');
  const [newThreshold, setNewThreshold] = useState(0.7);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);

  const fetchData = useCallback(async () => {
    try {
      const [cmdRes, histRes] = await Promise.all([
        api.get('/voice-trigger/commands'),
        api.get('/voice-trigger/history?limit=20'),
      ]);
      setCommands(cmdRes.data?.commands || []);
      setHistory(histRes.data?.history || []);
    } catch {
      toast.error('Failed to load voice trigger data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCreateCommand = async () => {
    if (!newPhrase.trim()) return;
    try {
      await api.post('/voice-trigger/commands', {
        phrase: newPhrase.trim().toLowerCase(),
        linked_action: newAction,
        confidence_threshold: newThreshold,
      });
      toast.success('Voice command created');
      setNewPhrase('');
      setShowAddForm(false);
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create command');
    }
  };

  const handleDeleteCommand = async (cmdId) => {
    try {
      await api.delete(`/voice-trigger/commands/${cmdId}`);
      toast.success('Command deleted');
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Cannot delete default command');
    }
  };

  const startListening = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      audioChunksRef.current = [];

      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await processAudio(audioBlob);
        stream.getTracks().forEach(t => t.stop());
        streamRef.current = null;
      };

      mediaRecorder.start();
      setIsListening(true);
      toast.info('Listening... Speak your escape command', { duration: 3000 });
    } catch {
      toast.error('Microphone access denied. Please allow microphone permissions.');
    }
  };

  const stopListening = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
    setIsListening(false);
  };

  const processAudio = async (audioBlob) => {
    setRecognizing(true);
    setLastResult(null);
    try {
      const formData = new FormData();
      formData.append('audio', audioBlob, 'voice-command.webm');
      const res = await api.post('/voice-trigger/recognize-audio', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      const data = res.data;
      setLastResult(data);

      if (data.triggered) {
        toast.success(`Voice command matched: "${data.matched_phrase}" → ${ACTION_META[data.linked_action]?.label || data.linked_action}`, { duration: 5000 });
        if (onVoiceTrigger) onVoiceTrigger(data);
      } else if (data.transcribed_text) {
        toast.warning(`No command matched for: "${data.transcribed_text}"`, { duration: 4000 });
      } else {
        toast.warning('Could not transcribe audio. Try speaking more clearly.', { duration: 4000 });
      }
      fetchData();
    } catch {
      toast.error('Voice recognition failed');
    } finally {
      setRecognizing(false);
    }
  };

  // Text-based recognition fallback
  const [textInput, setTextInput] = useState('');
  const handleTextRecognize = async () => {
    if (!textInput.trim()) return;
    setRecognizing(true);
    setLastResult(null);
    try {
      const res = await api.post('/voice-trigger/recognize', { transcribed_text: textInput.trim() });
      const data = res.data;
      setLastResult(data);
      if (data.triggered) {
        toast.success(`Matched: "${data.matched_phrase}" → ${ACTION_META[data.linked_action]?.label}`, { duration: 5000 });
        if (onVoiceTrigger) onVoiceTrigger(data);
      } else {
        toast.warning('No command matched');
      }
      setTextInput('');
      fetchData();
    } catch {
      toast.error('Recognition failed');
    } finally {
      setRecognizing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="voice-trigger-loading">
        <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl" data-testid="voice-trigger-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Mic className="w-7 h-7 text-teal-600" />
            Voice Escape Trigger
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Hands-free activation of escape mechanisms using voice commands
          </p>
        </div>
        <Badge variant="outline" className="text-xs font-mono bg-teal-50 border-teal-200 text-teal-700">
          {commands.filter(c => c.enabled).length} active commands
        </Badge>
      </div>

      {/* Live Voice Trigger */}
      <Card className="border-2 border-teal-200 bg-gradient-to-br from-teal-50 to-white" data-testid="voice-trigger-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Volume2 className="w-5 h-5 text-teal-600" />
            Live Voice Recognition
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Mic Button */}
          <div className="flex flex-col items-center gap-4">
            <button
              onClick={isListening ? stopListening : startListening}
              disabled={recognizing}
              className={`w-24 h-24 rounded-full flex items-center justify-center transition-all duration-300 shadow-lg ${
                isListening
                  ? 'bg-red-500 hover:bg-red-600 animate-pulse shadow-red-200'
                  : recognizing
                    ? 'bg-amber-400 cursor-wait shadow-amber-200'
                    : 'bg-teal-500 hover:bg-teal-600 shadow-teal-200 hover:shadow-teal-300'
              }`}
              data-testid="voice-trigger-mic-button"
            >
              {recognizing ? (
                <Loader2 className="w-10 h-10 text-white animate-spin" />
              ) : isListening ? (
                <MicOff className="w-10 h-10 text-white" />
              ) : (
                <Mic className="w-10 h-10 text-white" />
              )}
            </button>
            <p className="text-sm text-slate-500 text-center">
              {recognizing ? 'Processing audio...' : isListening ? 'Listening... Tap to stop' : 'Tap to start listening'}
            </p>
          </div>

          {/* Text Fallback */}
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleTextRecognize()}
              placeholder="Or type a command to test..."
              className="flex-1 px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
              data-testid="voice-trigger-text-input"
            />
            <Button
              size="sm"
              onClick={handleTextRecognize}
              disabled={recognizing || !textInput.trim()}
              data-testid="voice-trigger-text-submit"
            >
              {recognizing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            </Button>
          </div>

          {/* Last Result */}
          {lastResult && (
            <div className={`mt-3 p-3 rounded-lg border ${lastResult.triggered ? 'bg-green-50 border-green-200' : 'bg-slate-50 border-slate-200'}`} data-testid="voice-trigger-result">
              <div className="flex items-center gap-2 mb-1">
                {lastResult.triggered ? (
                  <CheckCircle className="w-4 h-4 text-green-600" />
                ) : (
                  <XCircle className="w-4 h-4 text-slate-400" />
                )}
                <span className="text-sm font-semibold">
                  {lastResult.triggered ? 'Command Triggered!' : 'No Match'}
                </span>
                <Badge variant="outline" className="text-xs ml-auto">
                  {Math.round(lastResult.confidence * 100)}% confidence
                </Badge>
              </div>
              <p className="text-xs text-slate-500">
                Heard: "<span className="font-medium text-slate-700">{lastResult.transcribed_text}</span>"
              </p>
              {lastResult.triggered && (
                <div className="mt-1 flex items-center gap-1.5">
                  <span className="text-xs text-slate-500">Action:</span>
                  <Badge className={`text-xs ${ACTION_META[lastResult.linked_action]?.bg} ${ACTION_META[lastResult.linked_action]?.border} text-slate-700`}>
                    {ACTION_META[lastResult.linked_action]?.label || lastResult.linked_action}
                  </Badge>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Configured Commands */}
      <Card data-testid="voice-commands-list">
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Settings className="w-5 h-5 text-slate-600" />
            Voice Commands
          </CardTitle>
          <Button size="sm" variant="outline" onClick={() => setShowAddForm(!showAddForm)} data-testid="add-command-toggle">
            <Plus className="w-4 h-4 mr-1" /> Add Command
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Add Command Form */}
          {showAddForm && (
            <div className="p-4 bg-slate-50 rounded-lg border border-slate-200 space-y-3" data-testid="add-command-form">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1">Trigger Phrase</label>
                <input
                  type="text"
                  value={newPhrase}
                  onChange={(e) => setNewPhrase(e.target.value)}
                  placeholder='e.g. "get me out" or "danger alert"'
                  className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                  data-testid="new-command-phrase"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1">Linked Action</label>
                  <select
                    value={newAction}
                    onChange={(e) => setNewAction(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-400"
                    data-testid="new-command-action"
                  >
                    <option value="fake_call">Escape Call</option>
                    <option value="fake_notification">Escape Notification</option>
                    <option value="sos">SOS Silent Mode</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-600 mb-1">
                    Confidence: {Math.round(newThreshold * 100)}%
                  </label>
                  <input
                    type="range"
                    min="0.3"
                    max="1"
                    step="0.05"
                    value={newThreshold}
                    onChange={(e) => setNewThreshold(parseFloat(e.target.value))}
                    className="w-full"
                    data-testid="new-command-threshold"
                  />
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <Button size="sm" variant="outline" onClick={() => setShowAddForm(false)}>Cancel</Button>
                <Button size="sm" onClick={handleCreateCommand} disabled={!newPhrase.trim()} data-testid="save-new-command">
                  <Plus className="w-4 h-4 mr-1" /> Save
                </Button>
              </div>
            </div>
          )}

          {/* Command List */}
          {commands.map((cmd) => {
            const meta = ACTION_META[cmd.linked_action] || ACTION_META.fake_call;
            const Icon = meta.icon;
            return (
              <div
                key={cmd.id}
                className={`flex items-center gap-3 p-3 rounded-lg border ${meta.bg} ${meta.border} transition-all hover:shadow-sm`}
                data-testid={`voice-command-${cmd.id}`}
              >
                <div className="w-9 h-9 rounded-full flex items-center justify-center" style={{ backgroundColor: meta.color + '20' }}>
                  <Icon className="w-4.5 h-4.5" style={{ color: meta.color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-800 truncate">
                    "{cmd.phrase}"
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <Badge variant="outline" className="text-xs">{meta.label}</Badge>
                    <span className="text-xs text-slate-400">
                      Threshold: {Math.round(cmd.confidence_threshold * 100)}%
                    </span>
                    {cmd.is_default && (
                      <Badge className="text-xs bg-slate-100 text-slate-500 border-slate-200">Default</Badge>
                    )}
                  </div>
                </div>
                {!cmd.is_default && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleDeleteCommand(cmd.id)}
                    className="text-red-400 hover:text-red-600 hover:bg-red-50"
                    data-testid={`delete-command-${cmd.id}`}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                )}
              </div>
            );
          })}

          {commands.length === 0 && (
            <p className="text-sm text-slate-400 text-center py-4">No voice commands configured</p>
          )}
        </CardContent>
      </Card>

      {/* Trigger History */}
      <Card data-testid="voice-trigger-history">
        <CardHeader>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="flex items-center justify-between w-full"
            data-testid="toggle-voice-history"
          >
            <CardTitle className="text-lg flex items-center gap-2">
              <History className="w-5 h-5 text-slate-600" />
              Recognition History
              <Badge variant="outline" className="text-xs ml-1">{history.length}</Badge>
            </CardTitle>
            {showHistory ? <ChevronUp className="w-5 h-5 text-slate-400" /> : <ChevronDown className="w-5 h-5 text-slate-400" />}
          </button>
        </CardHeader>
        {showHistory && (
          <CardContent className="space-y-2">
            {history.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-4">No recognition attempts yet</p>
            ) : (
              history.map((entry) => {
                const meta = ACTION_META[entry.linked_action];
                return (
                  <div
                    key={entry.id}
                    className={`flex items-center gap-3 p-2.5 rounded-lg border ${
                      entry.triggered ? 'bg-green-50 border-green-200' : 'bg-slate-50 border-slate-200'
                    }`}
                    data-testid={`history-entry-${entry.id}`}
                  >
                    {entry.triggered ? (
                      <CheckCircle className="w-4 h-4 text-green-500 shrink-0" />
                    ) : (
                      <XCircle className="w-4 h-4 text-slate-300 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-700 truncate">
                        "{entry.transcribed_text}"
                      </p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {entry.matched_phrase && (
                          <span className="text-xs text-green-600 font-medium">
                            Matched: "{entry.matched_phrase}"
                          </span>
                        )}
                        {meta && <Badge variant="outline" className="text-xs">{meta.label}</Badge>}
                        <span className="text-xs text-slate-400">
                          {Math.round(entry.confidence * 100)}%
                        </span>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-slate-400 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {new Date(entry.triggered_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </p>
                      <p className="text-xs text-slate-300">
                        {new Date(entry.triggered_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
          </CardContent>
        )}
      </Card>

      {/* How It Works */}
      <Card className="bg-slate-50 border-slate-200">
        <CardContent className="pt-4">
          <h3 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            How Voice Escape Works
          </h3>
          <ol className="text-xs text-slate-500 space-y-1 list-decimal list-inside">
            <li>Tap the microphone button and speak your escape phrase</li>
            <li>Audio is transcribed using OpenAI Whisper (deleted immediately after)</li>
            <li>Transcript is matched against your configured voice commands</li>
            <li>If a match is found, the linked escape action triggers automatically</li>
            <li>You can also test commands by typing in the text input</li>
          </ol>
        </CardContent>
      </Card>
    </div>
  );
};

export default VoiceTriggerPage;
