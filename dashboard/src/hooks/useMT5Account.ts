'use client';

import { useState, useEffect, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { MT5AccountStatus } from '@/types';

export function useMT5Account() {
  const [account, setAccount] = useState<MT5AccountStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAccount = useCallback(async () => {
    try {
      setLoading(true);
      const { data, error: err } = await supabase
        .from('mt5_account_status')
        .select('*')
        .eq('id', 1)
        .limit(1);

      if (err) throw err;
      if (data && data.length > 0) {
        setAccount(data[0]);
      } else {
        setAccount(null);
      }
      setError(null);
    } catch (err: any) {
      console.error('Erro ao buscar mt5_account_status:', err);
      setError(err?.message || 'Erro ao carregar conta MT5');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAccount();

    const channel = supabase
      .channel('realtime_mt5_account_hook')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'mt5_account_status' },
        (payload) => {
          if (payload.new) {
            setAccount(payload.new as MT5AccountStatus);
          }
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [fetchAccount]);

  return { account, setAccount, loading, error, refetch: fetchAccount };
}
