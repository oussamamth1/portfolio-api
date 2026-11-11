import { Injectable } from '@nestjs/common';
import { SupabaseCrudService } from '../common/supabase-crud.service.js';
import { SupabaseService } from '../supabase/supabase.service.js';

export interface Project {
  id: string;
  title: string;
  company: string | null;
  period: string | null;
  location: string | null;
  description: string | null;
  icon_key: string | null;
  category: string | null;
  technologies: string[];
  highlights: string[];
  status: string | null;
  github_url: string | null;
  app_store_url: string | null;
  play_store_url: string | null;
  video_id: string | null;
  image_url: string | null;
  portrait: boolean;
  sort_order: number;
  updated_at: string;
}

@Injectable()
export class ProjectsService extends SupabaseCrudService<Project> {
  constructor(supabase: SupabaseService) {
    super(supabase, 'projects');
  }
}
