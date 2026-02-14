import React, { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { ticketService } from '../../services/tickets';
import { organizationService } from '../../services/organizations';
import { useAuth } from '../../context/AuthContext';
import { useQuery } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { PaperClipIcon, CheckCircleIcon, SparklesIcon } from '@heroicons/react/24/outline';

const CreateTicket: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [files, setFiles] = useState<File[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [createdTicketData, setCreatedTicketData] = useState<any>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { register, handleSubmit, formState: { errors }, watch } = useForm();

  const { data: orgsData } = useQuery({
    queryKey: ['organizations'],
    queryFn: () => organizationService.getOrganizations({ limit: 1000 }),
  });

  const organizations = orgsData?.organizations || [];

  const onSubmit = async (data: any) => {
    setIsSubmitting(true);
    try {
      const ticketData = {
        ...data,
        user_id: user?.user_id || '',
        files: files.length > 0 ? files : undefined,
      };

      const result = await ticketService.createTicket(ticketData);
      setCreatedTicketData(result);
      setShowModal(true);
      toast.success('Ticket created successfully!');
    } catch (error: any) {
      toast.error(error.message || 'Failed to create ticket');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <div className="bg-white rounded-lg shadow-lg p-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-6">Create New Ticket</h1>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Organization
            </label>
            <div className="w-full px-4 py-3 bg-gray-100 border border-gray-300 rounded-lg text-gray-700">
              {user?.organization?.company_name || user?.companyid || 'Your Organization'}
            </div>
            {/* Hidden input to pass strict companyid to form handler (though we override it in onSubmit anyway) */}
            <input
              type="hidden"
              {...register('companyid', { value: user?.companyid })}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Title *
            </label>
            <input
              {...register('title', { required: 'Title is required' })}
              type="text"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="Brief description of the issue"
            />
            {errors.title && (
              <p className="mt-1 text-sm text-red-600">{errors.title.message as string}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Description *
            </label>
            <textarea
              {...register('description', { required: 'Description is required' })}
              rows={6}
              className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              placeholder="Detailed description of the issue..."
            />
            {errors.description && (
              <p className="mt-1 text-sm text-red-600">{errors.description.message as string}</p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Priority
              </label>
              <select
                {...register('priority')}
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
              >
                <option value="">Select priority</option>
                <option value="High">High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Attachments
            </label>
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
              <PaperClipIcon className="w-12 h-12 text-gray-400 mx-auto mb-4" />
              <input
                type="file"
                multiple
                onChange={handleFileChange}
                className="hidden"
                id="file-upload"
              />
              <label
                htmlFor="file-upload"
                className="cursor-pointer text-primary hover:underline"
              >
                Click to upload files
              </label>
              {files.length > 0 && (
                <div className="mt-4">
                  <p className="text-sm text-gray-600">{files.length} file(s) selected</p>
                  <ul className="mt-2 text-sm text-gray-500">
                    {files.map((file, idx) => (
                      <li key={idx}>{file.name}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          <div className="flex gap-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 bg-primary text-white py-3 rounded-lg font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex justify-center items-center"
            >
              {isSubmitting ? (
                <>
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                  Creating...
                </>
              ) : 'Create Ticket'}
            </button>
            <button
              type="button"
              onClick={() => navigate('/user/dashboard')}
              className="px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
      {/* Success Modal */}
      {showModal && createdTicketData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-center mb-6">
              <div className="bg-green-100 p-3 rounded-full">
                <CheckCircleIcon className="w-8 h-8 text-green-600" />
              </div>
            </div>

            <h2 className="text-2xl font-bold text-center text-gray-900 mb-2">Ticket Created Successfully!</h2>
            <p className="text-center text-gray-600 mb-6">Ticket #{createdTicketData.ticket_number}</p>

            <div className="space-y-6">
              {/* AI Classification */}
              <div className="bg-blue-50 p-4 rounded-lg">
                <h3 className="text-sm font-semibold text-blue-900 mb-3 flex items-center">
                  <SparklesIcon className="w-5 h-5 mr-2" />
                  AI Classification Results
                </h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-xs text-blue-700 uppercase tracking-wide">Category</span>
                    <p className="font-medium text-blue-900">{createdTicketData.classification?.category}</p>
                  </div>
                  <div>
                    <span className="text-xs text-blue-700 uppercase tracking-wide">Priority</span>
                    <p className="font-medium text-blue-900">{createdTicketData.classification?.priority}</p>
                  </div>
                </div>
                {createdTicketData.classification?.confidence && (
                  <div className="mt-3">
                    <span className="text-xs text-blue-700 uppercase tracking-wide">Confidence Score</span>
                    <div className="w-full bg-blue-200 rounded-full h-2 mt-1">
                      <div
                        className="bg-blue-600 h-2 rounded-full"
                        style={{ width: `${createdTicketData.classification.confidence * 100}%` }}
                      ></div>
                    </div>
                  </div>
                )}
              </div>

              {/* Extracted Metadata */}
              {createdTicketData.extracted_metadata && Object.keys(createdTicketData.extracted_metadata).length > 0 && (
                <div className="border border-gray-200 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-gray-900 mb-3">Extracted Information</h3>
                  <div className="grid grid-cols-2 gap-4">
                    {Object.entries(createdTicketData.extracted_metadata).map(([key, value]: [string, any]) => (
                      value && (
                        <div key={key}>
                          <span className="text-xs text-gray-500 uppercase tracking-wide">{key.replace(/_/g, ' ')}</span>
                          <p className="text-sm text-gray-900">{String(value)}</p>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-8 flex justify-end gap-3">
              <button
                onClick={() => navigate('/user/dashboard')}
                className="px-4 py-2 text-gray-600 hover:text-gray-900"
              >
                Go to Dashboard
              </button>
              <button
                onClick={() => navigate(`/user/tickets/${createdTicketData.ticket_number}`)}
                className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-primary/90"
              >
                View Ticket
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CreateTicket;
