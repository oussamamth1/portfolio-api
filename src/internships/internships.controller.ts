import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { CreateInternshipDto } from './dto/create-internship.dto.js';
import { UpdateInternshipDto } from './dto/update-internship.dto.js';
import { Internship, InternshipsService } from './internships.service.js';

@Controller()
export class InternshipsController {
  constructor(
    private readonly internshipsService: InternshipsService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/internships')
  async findByUsername(@Param('username') username: string): Promise<Internship[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.internshipsService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/internships')
  findOwn(@CurrentUser() user: User): Promise<Internship[]> {
    return this.internshipsService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/internships')
  create(@CurrentUser() user: User, @Body() dto: CreateInternshipDto): Promise<Internship> {
    return this.internshipsService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/internships/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateInternshipDto,
  ): Promise<Internship> {
    return this.internshipsService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/internships/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.internshipsService.remove(user.id, id);
  }
}
