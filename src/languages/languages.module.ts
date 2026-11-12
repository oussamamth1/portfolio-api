import { Module } from '@nestjs/common';
import { ProfileModule } from '../profile/profile.module.js';
import { LanguagesController } from './languages.controller.js';
import { LanguagesService } from './languages.service.js';

@Module({
  imports: [ProfileModule],
  controllers: [LanguagesController],
  providers: [LanguagesService],
})
export class LanguagesModule {}
