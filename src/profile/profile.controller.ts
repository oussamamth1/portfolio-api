import { Body, Controller, Get, Patch, UseGuards } from '@nestjs/common';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { UpdateProfileDto } from './dto/update-profile.dto.js';
import { Profile, ProfileService } from './profile.service.js';

@Controller('profile')
export class ProfileController {
  constructor(private readonly profileService: ProfileService) {}

  @Get()
  find(): Promise<Profile> {
    return this.profileService.find();
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch()
  update(@Body() dto: UpdateProfileDto): Promise<Profile> {
    return this.profileService.update(dto);
  }
}
