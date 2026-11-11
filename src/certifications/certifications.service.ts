import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Certification {
  id: string;
  name: string;
  issuer: string;
  date: string | null;
  status: string | null;
  credential_id: string | null;
  description: string | null;
  skills: string[];
  url: string | null;
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class CertificationsService extends SupabaseCrudService<Certification> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'certifications');
  }
}
