import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Language {
  id: string;
  language: string;
  level: number;
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class LanguagesService extends SupabaseCrudService<Language> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'languages');
  }
}
