import React from 'react';
import Skeleton from '../ui/Skeleton';

const DashboardSkeleton: React.FC = () => {
    return (
        <div className="p-6 space-y-6 animate-fade-in">
            {/* Header */}
            <div className="flex justify-between items-center mb-8">
                <div className="space-y-2">
                    <Skeleton className="h-8 w-64" /> {/* Title */}
                    <Skeleton className="h-4 w-48" /> {/* Subtitle */}
                </div>
                <Skeleton className="h-10 w-32" /> {/* Action Button */}
            </div>

            {/* Stats Cards Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                {[...Array(4)].map((_, i) => (
                    <div key={i} className="p-6 bg-white dark:bg-slate-800 rounded-xl border border-gray-100 dark:border-slate-700 shadow-sm">
                        <div className="flex justify-between items-start mb-4">
                            <Skeleton className="h-10 w-10 rounded-lg" />
                            <Skeleton className="h-4 w-8" />
                        </div>
                        <Skeleton className="h-8 w-16 mb-2" />
                        <Skeleton className="h-4 w-24" />
                    </div>
                ))}
            </div>

            {/* Charts / Main Content Area */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 bg-white dark:bg-slate-800 p-6 rounded-xl border border-gray-100 dark:border-slate-700">
                    <Skeleton className="h-6 w-48 mb-6" /> {/* Chart Title */}
                    <Skeleton className="h-64 w-full" /> {/* Chart Area */}
                </div>
                <div className="bg-white dark:bg-slate-800 p-6 rounded-xl border border-gray-100 dark:border-slate-700">
                    <Skeleton className="h-6 w-32 mb-6" />
                    <div className="space-y-4">
                        {[...Array(5)].map((_, i) => (
                            <div key={i} className="flex items-center gap-3">
                                <Skeleton className="h-8 w-8 rounded-full" />
                                <div className="space-y-1 flex-1">
                                    <Skeleton className="h-4 w-full" />
                                    <Skeleton className="h-3 w-2/3" />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Table Section */}
            <div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-100 dark:border-slate-700 overflow-hidden">
                <div className="p-6 border-b border-gray-100 dark:border-slate-700">
                    <Skeleton className="h-6 w-48" />
                </div>
                <div className="p-6 space-y-4">
                    {[...Array(5)].map((_, i) => (
                        <Skeleton key={i} className="h-12 w-full" />
                    ))}
                </div>
            </div>
        </div>
    );
};

export default DashboardSkeleton;
