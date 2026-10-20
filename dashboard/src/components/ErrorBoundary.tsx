'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary capturou erro:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="p-4 bg-slate-900 border border-rose-500/50 rounded-xl text-rose-300 font-mono text-xs">
            <span>Erro ao renderizar componente 3D: {this.state.error?.message}</span>
            <button
              onClick={() => this.setState({ hasError: false })}
              className="ml-4 px-2 py-1 rounded bg-rose-950 border border-rose-500 text-rose-200 text-xs"
            >
              Tentar novamente
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
