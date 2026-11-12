import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { CreateSkillDto } from './dto/create-skill.dto.js';
import { UpdateSkillDto } from './dto/update-skill.dto.js';
import { Skill, SkillsService } from './skills.service.js';

@Controller()
export class SkillsController {
  constructor(
    private readonly skillsService: SkillsService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/skills')
  async findByUsername(@Param('username') username: string): Promise<Skill[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.skillsService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/skills')
  findOwn(@CurrentUser() user: User): Promise<Skill[]> {
    return this.skillsService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/skills')
  create(@CurrentUser() user: User, @Body() dto: CreateSkillDto): Promise<Skill> {
    return this.skillsService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/skills/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateSkillDto,
  ): Promise<Skill> {
    return this.skillsService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/skills/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.skillsService.remove(user.id, id);
  }
}
