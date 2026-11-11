import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SupabaseClient, createClient } from '@supabase/supabase-js';
import WebSocket from 'ws';

@Injectable()
export class SupabaseService {
  readonly client: SupabaseClient;

  constructor(config: ConfigService) {
    const url = config.getOrThrow<string>('SUPABASE_URL');
    const serviceRoleKey = config.getOrThrow<string>('SUPABASE_SERVICE_ROLE_KEY');
    this.client = createClient(url, serviceRoleKey, {
      auth: { persistSession: false },
      realtime: { transport: WebSocket as never },
    });
  }
}
