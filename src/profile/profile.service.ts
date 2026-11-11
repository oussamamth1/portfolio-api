import { Injectable, InternalServerErrorException, NotFoundException } from '@nestjs/common';
import { SupabaseService } from '../supabase/supabase.service.js';
import { UpdateProfileDto } from './dto/update-profile.dto.js';

export interface Profile {
  id: string;
  name: string;
  title: string;
  tagline: string | null;
  bio: string | null;
  phone: string | null;
  avatar_url: string | null;
  resume_url: string | null;
  updated_at: string;
}

@Injectable()
export class ProfileService {
  constructor(private readonly supabase: SupabaseService) {}

  async find(): Promise<Profile> {
    const { data, error } = await this.supabase.client
      .from('profile')
      .select('*')
      .limit(1)
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException('Profile has not been created yet');
    return data as Profile;
  }

  async update(payload: UpdateProfileDto): Promise<Profile> {
    const current = await this.find();
    const { data, error } = await this.supabase.client
      .from('profile')
      .update({ ...payload, updated_at: new Date().toISOString() })
      .eq('id', current.id)
      .select()
      .single();
    if (error) throw new InternalServerErrorException(error.message);
    return data as Profile;
  }
}
