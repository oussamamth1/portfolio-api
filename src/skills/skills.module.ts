import { Module } from '@nestjs/common';
import { ProfileModule } from '../profile/profile.module.js';
import { SkillsController } from './skills.controller.js';
import { SkillsService } from './skills.service.js';

@Module({
  imports: [ProfileModule],
  controllers: [SkillsController],
  providers: [SkillsService],
})
export class SkillsModule {}
