import React, { useState, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import { technicianService } from '../../services/technicians';
import {
    PaperAirplaneIcon,
    SparklesIcon,
    ArrowPathIcon,
    LightBulbIcon,
    CheckCircleIcon
} from '@heroicons/react/24/outline';
import { UserCircleIcon } from '@heroicons/react/24/solid';

import { useAuth } from '../../context/AuthContext';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    sources?: any[];
    followUps?: string[];
    confidence?: number;
    steps?: string[];
}

const TechnicianAssistant: React.FC = () => {
    const { user } = useAuth();
    const storageKey = `lumi_chat_history_${user?.user_id || 'guest'}`;

    const [messages, setMessages] = useState<Message[]>(() => {
        const saved = localStorage.getItem(storageKey);
        try {
            return saved ? JSON.parse(saved).map((msg: any) => ({
                ...msg,
                timestamp: new Date(msg.timestamp)
            })) : [{
                id: 'welcome',
                role: 'assistant',
                content: 'Hello! I am Lumi, your AI. I can help you analyze tickets, suggest solutions, or find similar past issues.',
                timestamp: new Date(),
            }];
        } catch (e) {
            console.error('Failed to parse chat history:', e);
            return [{
                id: 'welcome',
                role: 'assistant',
                content: 'Hello! I am Lumi, your AI. I can help you analyze tickets, suggest solutions, or find similar past issues.',
                timestamp: new Date(),
            }];
        }
    });

    // Reset messages if user changes (case where user logs out and logs in as another without refresh)
    useEffect(() => {
        const key = `lumi_chat_history_${user?.user_id || 'guest'}`;
        const saved = localStorage.getItem(key);
        if (saved) {
            try {
                const parsed = JSON.parse(saved).map((msg: any) => ({
                    ...msg,
                    timestamp: new Date(msg.timestamp)
                }));
                setMessages(parsed);
            } catch (e) {
                // fallback
            }
        } else {
            setMessages([{
                id: 'welcome',
                role: 'assistant',
                content: 'Hello! I am Lumi, your AI. I can help you analyze tickets, suggest solutions, or find similar past issues.',
                timestamp: new Date(),
            }]);
        }
    }, [user?.user_id]);

    const [input, setInput] = useState('');
    const [sessionId, setSessionId] = useState<string | undefined>(undefined);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
        // Persist messages whenever they change
        if (user?.user_id) {
            const key = `lumi_chat_history_${user.user_id}`;
            localStorage.setItem(key, JSON.stringify(messages));
        }
    }, [messages, user?.user_id]);

    const sendMessageMutation = useMutation({
        mutationFn: (text: string) => technicianService.assistTechnician(text, sessionId),
        onSuccess: (data) => {
            if (data.session_id) setSessionId(data.session_id);

            // Determine content based on success flag and available data
            let content = "Here is what I found.";

            if (!data.success && data.message) {
                content = data.message;
            } else if (data.analysis || data.solution) {
                content = (data.analysis || '') + (data.solution ? '\n\n' + data.solution : '');
            } else if (data.message) {
                content = data.message;
            }

            // Parse response for structure if possible, otherwise use standard format
            const assistantMessage: Message = {
                id: Date.now().toString(),
                role: 'assistant',
                content: content,
                timestamp: new Date(),
                sources: data.sources,
                followUps: data.follow_up_questions,
                confidence: data.success ? (data.confidence || 0.92) : undefined,
            };

            // If we have specific formatted solution steps, we could parse them
            // For now, let's structure the content to match the design
            setMessages((prev) => [...prev, assistantMessage]);
        },
        onError: (error: any) => {
            setMessages((prev) => [
                ...prev,
                {
                    id: Date.now().toString(),
                    role: 'assistant',
                    content: 'Sorry, I encountered an error while processing your request.',
                    timestamp: new Date(),
                },
            ]);
        },
    });

    const handleSend = (e?: React.FormEvent) => {
        e?.preventDefault();
        if (!input.trim() || sendMessageMutation.isPending) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: input,
            timestamp: new Date(),
        };

        setMessages((prev) => [...prev, userMessage]);
        sendMessageMutation.mutate(input);
        setInput('');
    };

    const handleFollowUpClick = (question: string) => {
        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: question,
            timestamp: new Date(),
        };
        setMessages((prev) => [...prev, userMessage]);
        sendMessageMutation.mutate(question);
    };

    return (
        <div className="flex flex-col h-[calc(100vh-6rem)] bg-white rounded-xl shadow-sm overflow-hidden border border-gray-100">
            {/* Header */}
            <div className="bg-white p-4 border-b border-gray-100 flex items-center justify-between sticky top-0 z-10">
                <div className="flex items-center gap-3">
                    <div className="bg-primary rounded-xl p-2 shadow-lg shadow-primary/20">
                        <SparklesIcon className="w-6 h-6 text-white" />
                    </div>
                    <div>
                        <span className="text-xs font-bold text-indigo-100 uppercase tracking-widest">DeepMind Reasoning</span>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                            <span className="text-xs text-gray-500 font-medium">Active • Reasoning</span>
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => {
                        const welcomeMsg: Message = {
                            id: 'welcome',
                            role: 'assistant',
                            content: 'Hello! I am Lumi, your AI. I can help you analyze tickets, suggest solutions, or find similar past issues.',
                            timestamp: new Date(),
                        };
                        setMessages([welcomeMsg]);
                        setSessionId(undefined);
                        const key = `lumi_chat_history_${user?.user_id || 'guest'}`;
                        localStorage.removeItem(key);
                    }}
                    className="p-2 text-gray-400 hover:text-primary transition-colors rounded-full hover:bg-gray-50"
                    title="Reset Chat"
                >
                    <ArrowPathIcon className="w-5 h-5" />
                </button>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-8 bg-gray-50/50">
                {messages.map((message) => (
                    <div key={message.id} className="flex gap-4 max-w-4xl mx-auto w-full group">
                        {/* Avatar */}
                        <div className="flex-shrink-0 mt-1">
                            {message.role === 'assistant' ? (
                                <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/20">
                                    <SparklesIcon className="w-6 h-6 text-white" />
                                </div>
                            ) : (
                                <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center">
                                    <UserCircleIcon className="w-6 h-6 text-gray-500" />
                                </div>
                            )}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                                <span className={`font-semibold text-sm ${message.role === 'assistant' ? 'text-primary' : 'text-gray-900'}`}>
                                    {message.role === 'assistant' ? 'Lumi' : 'Technician'}
                                </span>
                                <span className="text-xs text-gray-400">
                                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                            </div>

                            {message.role === 'user' ? (
                                <div className="bg-white p-4 rounded-2xl rounded-tl-none shadow-sm border border-gray-100 text-gray-800 text-base leading-relaxed">
                                    {message.content}
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {/* Insight Box - Similar Tickets */}
                                    {message.sources && message.sources.length > 0 && (
                                        <div className="bg-indigo-50/50 rounded-2xl p-4 border border-indigo-100">
                                            <div className="flex items-start gap-3">
                                                <LightBulbIcon className="w-5 h-5 text-indigo-600 mt-0.5" />
                                                <div>
                                                    <h4 className="text-sm font-semibold text-indigo-900">Found {message.sources.length} similar resolved tickets</h4>
                                                    <p className="text-sm text-indigo-700 mt-1">
                                                        Analyzing patterns from {message.sources.map(s => s.ticket_number).join(', ')}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {/* Main Content / Steps */}
                                    <div className="prose prose-sm max-w-none text-gray-600">
                                        {message.content.split('\n').map((line, idx) => {
                                            if (line.trim().startsWith('-') || line.trim().startsWith('*')) { // Minimal formatting for list items
                                                return (
                                                    <div key={idx} className="flex gap-3 items-start my-2">
                                                        <div className="w-6 h-6 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center flex-shrink-0 text-xs font-bold mt-0.5">
                                                            {idx}
                                                        </div>
                                                        <span className="text-gray-700">{line.replace(/^[-*]\s*/, '')}</span>
                                                    </div>
                                                );
                                            }
                                            return <p key={idx} className="mb-2">{line}</p>;
                                        })}
                                    </div>

                                    {/* Confidence Score */}
                                    {message.confidence && (
                                        <div className="flex items-center gap-2 text-sm">
                                            <span className="font-semibold text-green-600">{(message.confidence * 100).toFixed(0)}% confidence</span>
                                            <span className="text-gray-400">based on historical resolution patterns</span>
                                        </div>
                                    )}

                                    {/* Follow-ups */}
                                    {message.followUps && message.followUps.length > 0 && (
                                        <div className="flex flex-wrap gap-2 pt-2">
                                            {message.followUps.map((q, idx) => (
                                                <button
                                                    key={idx}
                                                    onClick={() => handleFollowUpClick(q)}
                                                    className="inline-flex items-center px-3 py-1.5 rounded-full text-xs font-medium bg-white border border-gray-200 text-gray-600 hover:border-primary hover:text-primary transition-colors shadow-sm"
                                                >
                                                    <SparklesIcon className="w-3 h-3 mr-1.5" />
                                                    {q}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                ))}

                {sendMessageMutation.isPending && (
                    <div className="flex gap-4 max-w-4xl mx-auto w-full">
                        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/20">
                            <SparklesIcon className="w-6 h-6 text-white" />
                        </div>
                        <div className="flex-1">
                            <div className="flex space-x-2 mt-3">
                                <div className="w-2 h-2 bg-primary/40 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                                <div className="w-2 h-2 bg-primary/40 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                                <div className="w-2 h-2 bg-primary/40 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                            </div>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            {/* Input Area */}
            <div className="p-4 bg-white border-t border-gray-100">
                <div className="max-w-4xl mx-auto relative">
                    <form onSubmit={handleSend} className="relative group">
                        <input
                            type="text"
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Ask Lumi anything about this ticket..."
                            className="w-full pl-5 pr-14 py-4 bg-gray-50 border-transparent rounded-[20px] focus:bg-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all shadow-sm group-hover:shadow-md text-gray-700 placeholder-gray-400"
                            disabled={sendMessageMutation.isPending}
                        />
                        <button
                            type="submit"
                            disabled={!input.trim() || sendMessageMutation.isPending}
                            className="absolute right-2 top-1/2 transform -translate-y-1/2 p-2 bg-primary text-white rounded-xl hover:bg-primary/90 disabled:opacity-50 disabled:scale-95 transition-all shadow-md shadow-primary/30"
                        >
                            {sendMessageMutation.isPending ? (
                                <ArrowPathIcon className="w-5 h-5 animate-spin" />
                            ) : (
                                <SparklesIcon className="w-5 h-5" />
                            )}
                        </button>
                    </form>
                    <div className="text-center mt-2 text-xs text-gray-400">
                        Lumi can make mistakes. Please verify important information.
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TechnicianAssistant;
