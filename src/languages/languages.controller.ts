import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { CreateLanguageDto } from './dto/create-language.dto.js';
import { UpdateLanguageDto } from './dto/update-language.dto.js';
import { Language, LanguagesService } from './languages.service.js';

@Controller()
export class LanguagesController {
  constructor(
    private readonly languagesService: LanguagesService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/languages')
  async findByUsername(@Param('username') username: string): Promise<Language[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.languagesService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/languages')
  findOwn(@CurrentUser() user: User): Promise<Language[]> {
    return this.languagesService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/languages')
  create(@CurrentUser() user: User, @Body() dto: CreateLanguageDto): Promise<Language> {
    return this.languagesService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/languages/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateLanguageDto,
  ): Promise<Language> {
    return this.languagesService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/languages/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.languagesService.remove(user.id, id);
  }
}
