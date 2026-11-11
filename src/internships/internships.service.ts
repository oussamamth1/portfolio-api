import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Internship {
  id: string;
  company: string;
  role: string;
  period: string | null;
  location: string | null;
  type: string | null;
  is_current: boolean;
  description: string | null;
  highlights: string[];
  techs: string[];
  logo_url: string | null;
  demo_url: string | null;
  video_id: string | null;
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class InternshipsService extends SupabaseCrudService<Internship> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'internships');
  }
}
