'use client';

import { useState, useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';

const SOCKET_URL = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8080';

interface SocketData {
  equity?: {
    equity: number;
    capital: number;
    unrealized: number;
    open_positions: number;
  };
  regime?: {
    regime: string;
    confidence: number;
    probabilities: Record<string, number>;
  };
  positions?: any[];
  balance?: any;
}

interface UseSocketReturn {
  connected: boolean;
  data: SocketData;
  error: string | null;
}

export function useSocket(): UseSocketReturn {
  const socketRef = useRef<Socket | null>(null);
  const dataRef = useRef<SocketData>({});
  const [, forceUpdate] = useState(0);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const socket = io(SOCKET_URL, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
    });

    socket.on('connect', () => {
      console.log('[SOCKET] Socket.IO connected');
      setConnected(true);
      setError(null);
    });

    socket.on('disconnect', () => {
      console.log('[SOCKET] Socket.IO disconnected');
      setConnected(false);
    });

    socket.on('connect_error', (err) => {
      console.error('Socket.IO connection error:', err);
      setError(err.message);
      setConnected(false);
    });

    // Handle equity updates (balance, unrealized PnL)
    socket.on('equity_update', (data: any) => {
      dataRef.current.equity = data.data;
      forceUpdate(n => n + 1);
    });

    // Handle regime updates
    socket.on('regime_update', (data: any) => {
      dataRef.current.regime = data.data;
      forceUpdate(n => n + 1);
    });

    // Handle position updates
    socket.on('position_update', (data: any) => {
      const event = data.event;
      const position = data.data;
      
      if (event === 'open') {
        if (!dataRef.current.positions) dataRef.current.positions = [];
        dataRef.current.positions.push(position);
      } else if (event === 'close') {
        if (dataRef.current.positions) {
          dataRef.current.positions = dataRef.current.positions.filter(
            p => p.id !== position.id
          );
        }
      } else if (event === 'update') {
        if (dataRef.current.positions) {
          const idx = dataRef.current.positions.findIndex(p => p.id === position.id);
          if (idx !== -1) {
            dataRef.current.positions[idx] = position;
          }
        }
      }
      forceUpdate(n => n + 1);
    });

    // Handle balance updates
    socket.on('balance_update', (data: any) => {
      dataRef.current.balance = data.data;
      forceUpdate(n => n + 1);
    });

    socketRef.current = socket;

    return () => {
      socket.disconnect();
    };
  }, []);

  return {
    connected,
    data: dataRef.current,
    error,
  };
}
