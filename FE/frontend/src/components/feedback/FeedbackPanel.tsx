import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { feedbackService } from '../../services/feedback';
import toast from 'react-hot-toast';
import { StarIcon } from '@heroicons/react/24/solid';
import { StarIcon as StarIconOutline } from '@heroicons/react/24/outline';

interface FeedbackPanelProps {
    ticketNumber: string;
    isTechnician: boolean;
}

const FeedbackPanel: React.FC<FeedbackPanelProps> = ({ ticketNumber, isTechnician }) => {
    const [activeTab, setActiveTab] = useState<'classification' | 'assignment' | 'resolution'>('classification');

    // States for forms
    const [classificationFeedback, setClassificationFeedback] = useState({
        correct: true,
        expectedCategory: '',
        expectedPriority: '',
        comments: ''
    });

    const [assignmentFeedback, setAssignmentFeedback] = useState({
        correct: true,
        preferredTechId: '',
        comments: ''
    });

    const [resolutionFeedback, setResolutionFeedback] = useState({
        rating: 0,
        comments: ''
    });

    const submitFeedbackMutation = useMutation({
        mutationFn: (data: any) => {
            if (activeTab === 'classification') return feedbackService.submitClassificationFeedback(data);
            if (activeTab === 'assignment') return feedbackService.submitAssignmentFeedback(data);
            return feedbackService.submitResolutionFeedback(data);
        },
        onSuccess: () => {
            toast.success('Feedback submitted successfully');
            // Reset forms
            if (activeTab === 'classification') {
                setClassificationFeedback({ correct: true, expectedCategory: '', expectedPriority: '', comments: '' });
            } else if (activeTab === 'assignment') {
                setAssignmentFeedback({ correct: true, preferredTechId: '', comments: '' });
            } else {
                setResolutionFeedback({ rating: 0, comments: '' });
            }
        },
        onError: (error: any) => {
            toast.error(error.message || 'Failed to submit feedback');
        }
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        let payload: any = { ticket_number: ticketNumber };

        if (activeTab === 'classification') {
            payload = {
                ...payload,
                is_correct: classificationFeedback.correct,
                corrected_category: classificationFeedback.correct ? null : classificationFeedback.expectedCategory,
                corrected_priority: classificationFeedback.correct ? null : classificationFeedback.expectedPriority,
                comments: classificationFeedback.comments
            };
        } else if (activeTab === 'assignment') {
            payload = {
                ...payload,
                is_correct: assignmentFeedback.correct,
                preferred_tech_id: assignmentFeedback.correct ? null : assignmentFeedback.preferredTechId,
                comments: assignmentFeedback.comments
            };
        } else {
            payload = {
                ...payload,
                rating: resolutionFeedback.rating,
                comments: resolutionFeedback.comments
            };
        }

        submitFeedbackMutation.mutate(payload);
    };

    return (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 mt-6">
            <div className="px-6 py-4 border-b border-gray-200">
                <h3 className="text-lg font-medium text-gray-900">Feedback & Quality</h3>
            </div>

            <div className="p-6">
                <div className="flex space-x-4 mb-6 border-b border-gray-200">
                    <button
                        onClick={() => setActiveTab('classification')}
                        className={`pb-2 px-1 ${activeTab === 'classification' ? 'border-b-2 border-primary text-primary font-medium' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                        Classification
                    </button>
                    <button
                        onClick={() => setActiveTab('assignment')}
                        className={`pb-2 px-1 ${activeTab === 'assignment' ? 'border-b-2 border-primary text-primary font-medium' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                        Assignment
                    </button>
                    <button
                        onClick={() => setActiveTab('resolution')}
                        className={`pb-2 px-1 ${activeTab === 'resolution' ? 'border-b-2 border-primary text-primary font-medium' : 'text-gray-500 hover:text-gray-700'}`}
                    >
                        Resolution
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4">
                    {activeTab === 'classification' && (
                        <>
                            <div className="flex items-center gap-4">
                                <span className="text-sm font-medium text-gray-700">Was the AI classification correct?</span>
                                <div className="flex gap-4">
                                    <label className="flex items-center">
                                        <input
                                            type="radio"
                                            checked={classificationFeedback.correct}
                                            onChange={() => setClassificationFeedback({ ...classificationFeedback, correct: true })}
                                            className="mr-2 text-primary focus:ring-primary"
                                        />
                                        Yes
                                    </label>
                                    <label className="flex items-center">
                                        <input
                                            type="radio"
                                            checked={!classificationFeedback.correct}
                                            onChange={() => setClassificationFeedback({ ...classificationFeedback, correct: false })}
                                            className="mr-2 text-primary focus:ring-primary"
                                        />
                                        No
                                    </label>
                                </div>
                            </div>

                            {!classificationFeedback.correct && (
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Expected Category</label>
                                        <input
                                            type="text"
                                            value={classificationFeedback.expectedCategory}
                                            onChange={(e) => setClassificationFeedback({ ...classificationFeedback, expectedCategory: e.target.value })}
                                            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-700 mb-1">Expected Priority</label>
                                        <select
                                            value={classificationFeedback.expectedPriority}
                                            onChange={(e) => setClassificationFeedback({ ...classificationFeedback, expectedPriority: e.target.value })}
                                            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
                                        >
                                            <option value="">Select Priority</option>
                                            <option value="High">High</option>
                                            <option value="Medium">Medium</option>
                                            <option value="Low">Low</option>
                                            <option value="Critical">Critical</option>
                                        </select>
                                    </div>
                                </div>
                            )}
                        </>
                    )}

                    {activeTab === 'assignment' && (
                        <>
                            <div className="flex items-center gap-4">
                                <span className="text-sm font-medium text-gray-700">Was the ticket assigned correctly?</span>
                                <div className="flex gap-4">
                                    <label className="flex items-center">
                                        <input
                                            type="radio"
                                            checked={assignmentFeedback.correct}
                                            onChange={() => setAssignmentFeedback({ ...assignmentFeedback, correct: true })}
                                            className="mr-2 text-primary focus:ring-primary"
                                        />
                                        Yes
                                    </label>
                                    <label className="flex items-center">
                                        <input
                                            type="radio"
                                            checked={!assignmentFeedback.correct}
                                            onChange={() => setAssignmentFeedback({ ...assignmentFeedback, correct: false })}
                                            className="mr-2 text-primary focus:ring-primary"
                                        />
                                        No
                                    </label>
                                </div>
                            </div>

                            {!assignmentFeedback.correct && (
                                <div>
                                    <label className="block text-sm font-medium text-gray-700 mb-1">Preferred Technician ID</label>
                                    <input
                                        type="text"
                                        value={assignmentFeedback.preferredTechId}
                                        onChange={(e) => setAssignmentFeedback({ ...assignmentFeedback, preferredTechId: e.target.value })}
                                        className="w-full border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
                                    />
                                </div>
                            )}
                        </>
                    )}

                    {activeTab === 'resolution' && (
                        <div>
                            <label className="block text-sm font-medium text-gray-700 mb-2">Rate the resolution quality</label>
                            <div className="flex space-x-1 mb-4">
                                {[1, 2, 3, 4, 5].map((star) => (
                                    <button
                                        key={star}
                                        type="button"
                                        onClick={() => setResolutionFeedback({ ...resolutionFeedback, rating: star })}
                                        className="focus:outline-none"
                                    >
                                        {star <= resolutionFeedback.rating ? (
                                            <StarIcon className="w-8 h-8 text-yellow-400" />
                                        ) : (
                                            <StarIconOutline className="w-8 h-8 text-gray-300" />
                                        )}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Additional Comments</label>
                        <textarea
                            rows={3}
                            value={
                                activeTab === 'classification' ? classificationFeedback.comments :
                                    activeTab === 'assignment' ? assignmentFeedback.comments :
                                        resolutionFeedback.comments
                            }
                            onChange={(e) => {
                                const val = e.target.value;
                                if (activeTab === 'classification') setClassificationFeedback({ ...classificationFeedback, comments: val });
                                else if (activeTab === 'assignment') setAssignmentFeedback({ ...assignmentFeedback, comments: val });
                                else setResolutionFeedback({ ...resolutionFeedback, comments: val });
                            }}
                            className="w-full border-gray-300 rounded-md shadow-sm focus:ring-primary focus:border-primary"
                            placeholder="Add specific details about your feedback..."
                        />
                    </div>

                    <button
                        type="submit"
                        disabled={submitFeedbackMutation.isPending}
                        className="w-full bg-primary text-white py-2 px-4 rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50"
                    >
                        {submitFeedbackMutation.isPending ? 'Submitting...' : 'Submit Feedback'}
                    </button>
                </form>
            </div>
        </div>
    );
};

export default FeedbackPanel;
