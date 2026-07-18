import React from 'react';

export const SkeletonLoader = ({ lines = 4, height = '12px', gap = '12px' }) => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          style={{
            height,
            background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)',
            backgroundSize: '200% 100%',
            borderRadius: '6px',
            animation: 'skeleton-loading 1.5s infinite',
            width: i === lines - 1 ? '80%' : '100%',
          }}
        />
      ))}
    </div>
  );
};

export const SkeletonCard = () => {
  return (
    <div style={{
      padding: '16px',
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid rgba(255,255,255,0.04)',
      borderRadius: '12px',
      display: 'flex',
      gap: '12px',
      alignItems: 'flex-start',
    }}>
      {/* Score ring skeleton */}
      <div
        style={{
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)',
          backgroundSize: '200% 100%',
          animation: 'skeleton-loading 1.5s infinite',
          flexShrink: 0,
        }}
      />
      {/* Content skeleton */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div
          style={{
            height: '16px',
            background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)',
            backgroundSize: '200% 100%',
            animation: 'skeleton-loading 1.5s infinite',
            borderRadius: '4px',
            width: '60%',
          }}
        />
        <div
          style={{
            height: '12px',
            background: 'linear-gradient(90deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.1) 50%, rgba(255,255,255,0.05) 100%)',
            backgroundSize: '200% 100%',
            animation: 'skeleton-loading 1.5s infinite',
            borderRadius: '4px',
            width: '40%',
          }}
        />
      </div>
    </div>
  );
};

export default SkeletonLoader;
