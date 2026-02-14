import React from 'react';
import { cn } from '../../lib/utils'; // Assuming a utility exists or I'll create a simple one inline if needed.

// Simple class utility if 'cn' doesn't exist yet
const classNames = (...classes: (string | undefined | null | false)[]) => {
    return classes.filter(Boolean).join(' ');
};

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
    className?: string; // Add className prop for flexibility
}

const Skeleton: React.FC<SkeletonProps> = ({ className, ...props }) => {
    return (
        <div
            className={classNames(
                "animate-pulse rounded-md bg-gray-200 dark:bg-slate-700/50",
                className
            )}
            {...props}
        />
    );
};

export default Skeleton;
