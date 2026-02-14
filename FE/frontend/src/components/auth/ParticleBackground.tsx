import React, { useEffect, useRef } from 'react';

interface Particle {
    x: number;
    y: number;
    vx: number;
    vy: number;
    color: string;
    size: number;
    life: number;
}

const ParticleBackground: React.FC = () => {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        let particles: Particle[] = [];
        let animationFrameId: number;
        let width = canvas.width;
        let height = canvas.height;

        const colors = ['#6366f1', '#8b5cf6', '#ec4899', '#3b82f6']; // Indigo, Purple, Pink, Blue

        const resize = () => {
            if (canvas.parentElement) {
                canvas.width = canvas.parentElement.clientWidth;
                canvas.height = canvas.parentElement.clientHeight;
                width = canvas.width;
                height = canvas.height;
            }
        };

        const createParticle = (x?: number, y?: number): Particle => {
            return {
                x: x ?? Math.random() * width,
                y: y ?? Math.random() * height,
                vx: (Math.random() - 0.5) * 1.5,
                vy: (Math.random() - 0.5) * 1.5,
                color: colors[Math.floor(Math.random() * colors.length)],
                size: Math.random() * 2 + 1,
                life: Math.random() * 100 + 100
            };
        };

        const initParticles = () => {
            particles = [];
            const particleCount = Math.floor((width * height) / 8000); // Density
            for (let i = 0; i < particleCount; i++) {
                particles.push(createParticle());
            }
        };

        const draw = () => {
            ctx.clearRect(0, 0, width, height);

            // Update and draw particles
            particles.forEach((p, i) => {
                // Move
                p.x += p.vx;
                p.y += p.vy;

                // Bounce off walls (or wrap) - Let's wrap for flow
                if (p.x < 0) p.x = width;
                if (p.x > width) p.x = 0;
                if (p.y < 0) p.y = height;
                if (p.y > height) p.y = 0;

                // Draw Dot
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
                ctx.fillStyle = p.color;
                ctx.globalAlpha = 0.6;
                ctx.fill();
                ctx.globalAlpha = 1;
            });

            // Draw Connections (Constellation effect)
            ctx.strokeStyle = '#6366f1';
            ctx.lineWidth = 0.5;

            // Optimization: Only check neighbors (simple loop)
            // For true Antigravity swarm, we might not want lines, but user said "patern". 
            // The image shows dots. Let's stick to Dots with a Flow Field or just simple drift.
            // The user description "moving in pattern" suggests maybe a flow.
            // Let's add a sine wave influence to make it look "patterned" not just random brownian.

            const time = Date.now() * 0.001;
            particles.forEach(p => {
                // Add flow field influence
                const angle = (p.x * 0.005) + (p.y * 0.005) + time;
                p.vx += Math.sin(angle) * 0.02;
                p.vy += Math.cos(angle) * 0.02;

                // Speed limit
                const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
                if (speed > 2) {
                    p.vx = (p.vx / speed) * 2;
                    p.vy = (p.vy / speed) * 2;
                }
            });

            animationFrameId = requestAnimationFrame(draw);
        };

        window.addEventListener('resize', resize);
        resize();
        initParticles();
        draw();

        return () => {
            window.removeEventListener('resize', resize);
            cancelAnimationFrame(animationFrameId);
        };
    }, []);

    return <canvas ref={canvasRef} className="absolute inset-0 z-0 opacity-50" />;
};

export default ParticleBackground;
