import {
  ConflictException,
  Injectable,
  InternalServerErrorException,
  NotFoundException,
} from '@nestjs/common';
import { SupabaseService } from '../supabase/supabase.service.js';
import {
  CreateProfileDto,
  ProfileAnimation,
  ProfileTheme,
  SectionConfigItemDto,
} from './dto/create-profile.dto.js';
import { UpdateProfileDto } from './dto/update-profile.dto.js';

export interface Profile {
  id: string;
  user_id: string;
  username: string;
  name: string;
  title: string;
  tagline: string | null;
  bio: string | null;
  phone: string | null;
  avatar_url: string | null;
  resume_url: string | null;
  theme: ProfileTheme;
  section_config: SectionConfigItemDto[];
  animation: ProfileAnimation;
  updated_at: string;
}

@Injectable()
export class ProfileService {
  constructor(private readonly supabase: SupabaseService) {}

  async findOwn(userId: string): Promise<Profile> {
    const { data, error } = await this.supabase.client
      .from('profile')
      .select('*')
      .eq('user_id', userId)
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException('Profile has not been created yet');
    return data as Profile;
  }

  async findByUsername(username: string): Promise<Profile> {
    const { data, error } = await this.supabase.client
      .from('profile')
      .select('*')
      .eq('username', username)
      .maybeSingle();
    if (error) throw new InternalServerErrorException(error.message);
    if (!data) throw new NotFoundException(`No profile found for username "${username}"`);
    return data as Profile;
  }

  async create(userId: string, payload: CreateProfileDto): Promise<Profile> {
    const { data: existing } = await this.supabase.client
      .from('profile')
      .select('id')
      .eq('user_id', userId)
      .maybeSingle();
    if (existing) throw new ConflictException('Profile already exists for this user');

    const { data, error } = await this.supabase.client
      .from('profile')
      .insert({ ...payload, user_id: userId })
      .select()
      .single();
    if (error?.code === '23505') throw new ConflictException('Username is already taken');
    if (error) throw new InternalServerErrorException(error.message);
    return data as Profile;
  }

  async update(userId: string, payload: UpdateProfileDto): Promise<Profile> {
    const current = await this.findOwn(userId);
    const { data, error } = await this.supabase.client
      .from('profile')
      .update({ ...payload, updated_at: new Date().toISOString() })
      .eq('id', current.id)
      .select()
      .single();
    if (error?.code === '23505') throw new ConflictException('Username is already taken');
    if (error) throw new InternalServerErrorException(error.message);
    return data as Profile;
  }
}
