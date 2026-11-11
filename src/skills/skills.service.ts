import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Skill {
  id: string;
  category: string;
  icon_key: string | null;
  subject: string;
  level: number;
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class SkillsService extends SupabaseCrudService<Skill> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'skills');
  }
}
