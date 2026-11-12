import { Body, Controller, Delete, Get, Param, Patch, Post, UseGuards } from '@nestjs/common';
import type { User } from '@supabase/supabase-js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { SupabaseAuthGuard } from '../auth/supabase-auth.guard.js';
import { ProfileService } from '../profile/profile.service.js';
import { Certification, CertificationsService } from './certifications.service.js';
import { CreateCertificationDto } from './dto/create-certification.dto.js';
import { UpdateCertificationDto } from './dto/update-certification.dto.js';

@Controller()
export class CertificationsController {
  constructor(
    private readonly certificationsService: CertificationsService,
    private readonly profileService: ProfileService,
  ) {}

  @Get('u/:username/certifications')
  async findByUsername(@Param('username') username: string): Promise<Certification[]> {
    const profile = await this.profileService.findByUsername(username);
    return this.certificationsService.findAllFor(profile.user_id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Get('me/certifications')
  findOwn(@CurrentUser() user: User): Promise<Certification[]> {
    return this.certificationsService.findAllFor(user.id);
  }

  @UseGuards(SupabaseAuthGuard)
  @Post('me/certifications')
  create(@CurrentUser() user: User, @Body() dto: CreateCertificationDto): Promise<Certification> {
    return this.certificationsService.create(user.id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Patch('me/certifications/:id')
  update(
    @CurrentUser() user: User,
    @Param('id') id: string,
    @Body() dto: UpdateCertificationDto,
  ): Promise<Certification> {
    return this.certificationsService.update(user.id, id, dto);
  }

  @UseGuards(SupabaseAuthGuard)
  @Delete('me/certifications/:id')
  remove(@CurrentUser() user: User, @Param('id') id: string): Promise<void> {
    return this.certificationsService.remove(user.id, id);
  }
}
