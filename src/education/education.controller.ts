import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { CreateEducationDto } from './dto/create-education.dto.js';
import { UpdateEducationDto } from './dto/update-education.dto.js';
import { Education, EducationService } from './education.service.js';

@Controller()
export class EducationController {
  constructor(
    private readonly educationService: EducationService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/education')
  async findByUsername(@Param('username') username: string): Promise<Education[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.educationService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/education')
  findOwn(@CurrentUser() user: User): Promise<Education[]> {
    return this.educationService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/education')
  create(@CurrentUser() user: User, @Body() dto: CreateEducationDto): Promise<Education> {
    return this.educationService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/education/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateEducationDto,
  ): Promise<Education> {
    return this.educationService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/education/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.educationService.remove(user.id, id);
  }
}
