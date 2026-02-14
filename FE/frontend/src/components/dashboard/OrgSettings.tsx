import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../ui/card";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { AlertCircle, Save, Trash2 } from "lucide-react";

const OrgSettings: React.FC = () => {
    const { user } = useAuth();
    const [loading, setLoading] = useState(false);

    // Placeholder state for form fields
    const [orgName, setOrgName] = useState(user?.organization?.company_name || '');
    const [contactEmail, setContactEmail] = useState(user?.organization?.company_email || '');

    const handleSave = async () => {
        setLoading(true);
        // Simulate API call
        setTimeout(() => setLoading(false), 1000);
    };

    return (
        <div className="max-w-4xl mx-auto space-y-8">
            <div>
                <h2 className="text-3xl font-bold tracking-tight text-gray-900">Settings</h2>
                <p className="text-gray-500 mt-1">Manage your organization profile and preferences.</p>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>Organization Profile</CardTitle>
                    <CardDescription>Update your company details and contact information.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label htmlFor="org-id">Organization ID</Label>
                            <Input id="org-id" value={user?.companyid || ''} disabled className="bg-gray-50 font-mono text-gray-500" />
                            <p className="text-xs text-muted-foreground">This ID is unique and cannot be changed.</p>
                        </div>
                        <div className="space-y-2">
                            <Label htmlFor="plan">Current Plan</Label>
                            <Input id="plan" value="Enterprise Plan" disabled className="bg-indigo-50 text-indigo-700 font-semibold border-indigo-100" />
                        </div>
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="org-name">Company Name</Label>
                        <Input
                            id="org-name"
                            value={orgName}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setOrgName(e.target.value)}
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="contact-email">Contact Email</Label>
                        <Input
                            id="contact-email"
                            type="email"
                            value={contactEmail}
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setContactEmail(e.target.value)}
                        />
                    </div>

                    <div className="pt-4 flex justify-end">
                        <Button onClick={handleSave} disabled={loading} className="bg-indigo-600 hover:bg-indigo-700">
                            {loading ? "Saving..." : <><Save className="w-4 h-4 mr-2" /> Save Changes</>}
                        </Button>
                    </div>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>System Preferences</CardTitle>
                    <CardDescription>Configure automation and notification settings.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="flex items-center justify-between py-2 border-b border-gray-100">
                        <div>
                            <h4 className="text-sm font-medium text-gray-900">Auto-assign Tickets</h4>
                            <p className="text-xs text-gray-500">Automatically route tickets to available technicians based on workload.</p>
                        </div>
                        <div className="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2 bg-indigo-600">
                            <span className="translate-x-5 pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"></span>
                        </div>
                    </div>

                    <div className="flex items-center justify-between py-2">
                        <div>
                            <h4 className="text-sm font-medium text-gray-900">Email Notifications</h4>
                            <p className="text-xs text-gray-500">Receive weekly summary reports via email.</p>
                        </div>
                        <div className="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-600 focus:ring-offset-2 bg-gray-200">
                            <span className="translate-x-0 pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"></span>
                        </div>
                    </div>
                </CardContent>
            </Card>

            <Card className="border-red-100 bg-red-50/30">
                <CardHeader>
                    <CardTitle className="text-red-600 flex items-center gap-2">
                        <AlertCircle className="w-5 h-5" /> Danger Zone
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex items-center justify-between">
                        <div>
                            <h4 className="text-sm font-medium text-gray-900">Delete Organization</h4>
                            <p className="text-xs text-gray-500">Permanently delete your organization and all associated data. This action cannot be undone.</p>
                        </div>
                        <Button variant="destructive" className="bg-red-600 hover:bg-red-700 text-white">
                            <Trash2 className="w-4 h-4 mr-2" /> Delete Organization
                        </Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
};

export default OrgSettings;
