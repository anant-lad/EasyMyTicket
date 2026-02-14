import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { adminService } from '../../services/admin';
import { Settings, Save, ToggleLeft, ToggleRight, Mail, Shield, AlertTriangle } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useAuth } from '../../context/AuthContext';

const GlobalSettings: React.FC = () => {
    const { user } = useAuth();
    const queryClient = useQueryClient();

    const { data: settingsResponse, isLoading } = useQuery({
        queryKey: ['global-settings'],
        queryFn: () => adminService.getSettings()
    });

    const updateSettingMutation = useMutation({
        mutationFn: ({ key, value }: { key: string, value: any }) =>
            adminService.updateSetting(key, value, user?.user_id || 'admin'),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['global-settings'] });
            toast.success('Setting updated successfully');
        },
        onError: () => toast.error('Failed to update setting')
    });

    const settings = settingsResponse?.settings || {};

    const handleToggle = (key: string, currentValue: boolean) => {
        updateSettingMutation.mutate({ key, value: !currentValue });
    };

    const FeatureToggle = ({ label, description, settingKey, icon: Icon }: any) => {
        const isEnabled = settings[settingKey] === true; // Simplified for demo, assumes direct boolean or needs JSON parsing handling

        return (
            <div className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200 shadow-sm">
                <div className="flex items-center gap-4">
                    <div className="p-2 bg-gray-50 text-gray-600 rounded-lg">
                        <Icon className="w-6 h-6" />
                    </div>
                    <div>
                        <h3 className="font-bold text-gray-900">{label}</h3>
                        <p className="text-sm text-gray-500">{description}</p>
                    </div>
                </div>
                <button
                    onClick={() => handleToggle(settingKey, isEnabled)}
                    disabled={updateSettingMutation.isPending}
                    className={`transition-colors ${isEnabled ? 'text-indigo-600' : 'text-gray-400'}`}
                >
                    {isEnabled ? <ToggleRight className="w-10 h-10" /> : <ToggleLeft className="w-10 h-10" />}
                </button>
            </div>
        );
    };

    if (isLoading) return <div>Loading...</div>;

    return (
        <div className="max-w-4xl mx-auto space-y-8">
            <div>
                <h1 className="text-2xl font-bold text-gray-900">Global Settings</h1>
                <p className="text-gray-500 mt-1">Configure system-wide parameters and feature flags</p>
            </div>

            <div className="space-y-6">
                <h2 className="text-lg font-bold text-gray-900 border-b border-gray-200 pb-2">Feature Flags</h2>
                <div className="space-y-4">
                    <FeatureToggle
                        label="AI Auto-Classification"
                        description="Enable LLM-based ticket classification and metadata extraction"
                        settingKey="feature_ai_classification"
                        icon={Settings}
                    />
                    <FeatureToggle
                        label="Smart Assignment"
                        description="Automatically assign tickets to technicians based on skills"
                        settingKey="feature_smart_assignment"
                        icon={Shield}
                    />
                </div>

                <h2 className="text-lg font-bold text-gray-900 border-b border-gray-200 pb-2 pt-4">System Maintenance</h2>
                <div className="space-y-4">
                    <FeatureToggle
                        label="Maintenance Mode"
                        description="Prevent non-admin users from accessing the system"
                        settingKey="system_maintenance_mode"
                        icon={AlertTriangle}
                    />
                    <FeatureToggle
                        label="Email Notifications"
                        description="Global switch for all system email notifications"
                        settingKey="system_email_notifications"
                        icon={Mail}
                    />
                </div>
            </div>
        </div>
    );
};

export default GlobalSettings;
