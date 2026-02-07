
export const formatDate = (isoString?: string): string => {
    if (!isoString) return '-';
    return new Date(isoString).toLocaleString([], {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
};

export const formatBytes = (bytes?: number): string => {
    if (bytes === undefined || bytes === null) return '-';
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
};

export const getPriorityColor = (priority: string): string => {
    switch (priority) {
        case 'High': return 'bg-red-100 text-red-800 border-red-200';
        case 'Medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
        case 'Low': return 'bg-green-100 text-green-800 border-green-200';
        case 'Critical': return 'bg-red-200 text-red-900 border-red-300';
        default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
};

export const getStatusColor = (status: string): string => {
    switch (status) {
        case 'Open': case 'TO DO': return 'bg-blue-100 text-blue-800 border-blue-200';
        case 'In Progress': return 'bg-yellow-100 text-yellow-800 border-yellow-200';
        case 'Resolved': case 'Resolution Planned': return 'bg-purple-100 text-purple-800 border-purple-200';
        case 'Closed': return 'bg-gray-100 text-gray-800 border-gray-200';
        default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
};
