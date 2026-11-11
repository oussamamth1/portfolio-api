import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Education {
  id: string;
  institution: string;
  degree: string;
  location: string | null;
  period: string | null;
  status: string | null;
  description: string | null;
  coursework: string[];
  achievements: string[];
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class EducationService extends SupabaseCrudService<Education> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'education');
  }
}
