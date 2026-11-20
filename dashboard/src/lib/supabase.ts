import { createClient } from '@supabase/supabase-js';

// Navegador: SOMENTE a chave pública (anon/publishable). O painel só lê; quem escreve é o processo
// run_supabase_sync.py na VPS, com a chave secreta guardada no .env do servidor (nunca em NEXT_PUBLIC_*).
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

if (supabaseAnonKey.startsWith('sb_secret')) {
  throw new Error('NEXT_PUBLIC_SUPABASE_ANON_KEY é uma chave SECRETA: use a chave pública (anon/publishable).');
}

export const supabase = createClient(
  supabaseUrl || 'https://placeholder.supabase.co',
  supabaseAnonKey || 'placeholder-key',
  { realtime: { params: { eventsPerSecond: 20 } } },
);
