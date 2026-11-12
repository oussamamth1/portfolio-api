import { Body, Controller, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import type { User } from '@supabase/supabase-js';
import { CreateProfileDto } from './dto/create-profile.dto.js';
import { UpdateProfileDto } from './dto/update-profile.dto.js';
import { Profile, ProfileService } from './profile.service.js';

@Controller()
export class ProfileController {
  constructor(private readonly profileService: ProfileService) {}

  @Get('u/:username/profile')
  findByUsername(@Param('username') username: string): Promise<Profile> {
    return this.profileService.findByUsername(username);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/profile')
  findOwn(@CurrentUser() user: User): Promise<Profile> {
    return this.profileService.findOwn(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/profile')
  create(@CurrentUser() user: User, @Body() dto: CreateProfileDto): Promise<Profile> {
    return this.profileService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/profile')
  update(@CurrentUser() user: User, @Body() dto: UpdateProfileDto): Promise<Profile> {
    return this.profileService.update(user.id, dto);
  }
}
